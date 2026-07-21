"""
Publishes the read-path tables the cloud app needs (embeddings, track metadata,
labels) from the local DuckDB catalog to parquet files, and uploads them
to Cloudflare R2 (S3-compatible) object storage.

This is the bridge between the heavy local pipeline (ONNX embedding, Plex sync,
tagging — all writing the local catalog) and the free, read-only cloud app, which
reads these parquet files instead of connecting to the local database.

Split into pure export (parquet writing, testable without credentials) and upload
(R2), so the export can be verified locally before any cloud setup exists.
"""
import logging
from datetime import timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from music_embeddings import config

logger = logging.getLogger("music_embeddings.publish")

# pyarrow and database are only needed for the local export path (publish CLI
# command), never for the cloud read path - importing them lazily (inside the
# functions that use them, below) means cloud.py/cloud_history.py can import this
# module for its R2 client/key constants without needing either package installed;
# neither is pre-bundled in DO's Python runtime nor listed in any Function's
# requirements.txt, so a module-level import here would break every Function.

EMBEDDING_DIM = 1280

# Object keys within the R2 bucket (the cloud app reads these exact names)
EMBEDDINGS_KEY = "embeddings.parquet"
TRACKS_KEY = "tracks.parquet"
LABELS_KEY = "labels.parquet"


def _parse_embedding(value) -> np.ndarray:
    """
    Normalize a stored embedding into a float32 vector. DuckDB returns FLOAT[1280]
    array columns as tuples; legacy exports may hand us strings like '[0.1,0.2,...]'.
    Mirror of tagger._parse_embedding to avoid importing that sklearn-heavy module.
    """
    if isinstance(value, str):
        return np.fromstring(value.strip().lstrip("[").rstrip("]"), sep=",", dtype=np.float32)
    return np.asarray(value, dtype=np.float32)


def export_embeddings_parquet(conn, out_dir: Path) -> Path:
    """
    Export (sha256, embedding) from track_embeddings. Embeddings are stored as
    float16 fixed-size lists to roughly halve the file size; the precision loss is
    irrelevant to cosine-similarity ranking and keeps the cloud working set small.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    with conn.cursor() as cur:
        cur.execute("SELECT sha256, embedding FROM embedding.track_embeddings ORDER BY sha256;")
        rows = cur.fetchall()

    if not rows:
        logger.warning("No embeddings found in track_embeddings; writing empty file.")

    shas: List[str] = []
    vecs: List[np.ndarray] = []
    for sha, emb in rows:
        vec = _parse_embedding(emb)
        if vec.shape[0] != EMBEDDING_DIM:
            logger.warning("Skipping %s: embedding dim %d != %d", sha, vec.shape[0], EMBEDDING_DIM)
            continue
        shas.append(sha)
        vecs.append(vec)

    if vecs:
        mat = np.vstack(vecs).astype(np.float16)
        flat = pa.array(mat.reshape(-1), type=pa.float16())
        emb_col = pa.FixedSizeListArray.from_arrays(flat, EMBEDDING_DIM)
    else:
        emb_col = pa.array([], type=pa.list_(pa.float16()))

    table = pa.table({"sha256": pa.array(shas, type=pa.string()), "embedding": emb_col})
    out_path = out_dir / EMBEDDINGS_KEY
    pq.write_table(table, out_path, compression="zstd")
    logger.info("Wrote %d embeddings -> %s", len(shas), out_path)
    return out_path


def export_tracks_parquet(conn, out_dir: Path) -> Path:
    """
    Export the per-track metadata the cloud read path needs from plex_track_metadata:
    identity, play history (for the recent-listening feature and discovery bias), and
    display fields.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    with conn.cursor() as cur:
        cur.execute("""
            SELECT sha256, plex_rating_key, artist_name, album_name, track_title,
                   play_count, last_played_at, genres, moods
            FROM embedding.plex_track_metadata
            WHERE sha256 IS NOT NULL
            ORDER BY sha256;
        """)
        rows = cur.fetchall()

    # Store last_played_at as naive UTC (tz stripped) so readers don't need the tzdata
    # package to deserialize; all values are UTC and DuckDB comparisons still work.
    def _naive_utc(dt):
        if dt is None:
            return None
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    table = pa.table({
        "sha256": pa.array([r[0] for r in rows], type=pa.string()),
        "rating_key": pa.array([r[1] for r in rows], type=pa.int64()),
        "artist_name": pa.array([r[2] for r in rows], type=pa.string()),
        "album_name": pa.array([r[3] for r in rows], type=pa.string()),
        "track_title": pa.array([r[4] for r in rows], type=pa.string()),
        "play_count": pa.array([r[5] for r in rows], type=pa.int64()),
        "last_played_at": pa.array([_naive_utc(r[6]) for r in rows], type=pa.timestamp("us")),
        "genres": pa.array([r[7] for r in rows], type=pa.list_(pa.string())),
        "moods": pa.array([r[8] for r in rows], type=pa.list_(pa.string())),
    })
    out_path = out_dir / TRACKS_KEY
    pq.write_table(table, out_path, compression="zstd")
    logger.info("Wrote %d track metadata rows -> %s", len(rows), out_path)
    return out_path


def export_labels_parquet(conn, out_dir: Path) -> Path:
    """
    Export the tall (sha256, source, label, probability) table used for label
    centroids and mood/style/genre autocomplete.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    with conn.cursor() as cur:
        cur.execute("SELECT sha256, source, label, probability FROM embedding.track_labels;")
        rows = cur.fetchall()

    table = pa.table({
        "sha256": pa.array([r[0] for r in rows], type=pa.string()),
        "source": pa.array([r[1] for r in rows], type=pa.string()),
        "label": pa.array([r[2] for r in rows], type=pa.string()),
        "probability": pa.array([r[3] for r in rows], type=pa.float32()),
    })
    out_path = out_dir / LABELS_KEY
    pq.write_table(table, out_path, compression="zstd")
    logger.info("Wrote %d label rows -> %s", len(rows), out_path)
    return out_path


def export_all(out_dir: Optional[Path] = None, conn=None) -> Dict[str, Path]:
    """Export all three parquet files locally. Returns {key: path}."""
    out_dir = Path(out_dir) if out_dir else (config.PROJECT_ROOT / "data" / "publish")
    out_dir.mkdir(parents=True, exist_ok=True)

    close_conn = False
    if conn is None:
        from music_embeddings.database import get_connection
        conn = get_connection()
        close_conn = True
    try:
        return {
            EMBEDDINGS_KEY: export_embeddings_parquet(conn, out_dir),
            TRACKS_KEY: export_tracks_parquet(conn, out_dir),
            LABELS_KEY: export_labels_parquet(conn, out_dir),
        }
    finally:
        if close_conn:
            conn.close()


def get_r2_client():
    """Build a boto3 S3 client pointed at Cloudflare R2. Raises if unconfigured."""
    import boto3
    from botocore.config import Config

    if not (config.R2_ACCESS_KEY_ID and config.R2_SECRET_ACCESS_KEY and config.R2_ENDPOINT_URL):
        raise ValueError(
            "R2 is not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, and "
            "R2_SECRET_ACCESS_KEY in your environment/.env."
        )
    # Fail fast (a handful of seconds) rather than hanging on botocore's much longer
    # defaults - if R2 is genuinely unreachable from wherever this runs, we want a
    # clear, quick error instead of eating a Function's entire timeout budget silently.
    boto_config = Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 2})
    return boto3.client(
        "s3",
        endpoint_url=config.R2_ENDPOINT_URL,
        aws_access_key_id=config.R2_ACCESS_KEY_ID,
        aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=boto_config,
    )


def upload_to_r2(paths: Dict[str, Path], client=None) -> None:
    """Upload each {key: path} to the configured R2 bucket under that key."""
    client = client or get_r2_client()
    bucket = config.R2_BUCKET
    for key, path in paths.items():
        client.upload_file(str(path), bucket, key)
        size_mb = path.stat().st_size / (1024 * 1024)
        logger.info("Uploaded %s (%.1f MB) -> r2://%s/%s", path.name, size_mb, bucket, key)


def publish(out_dir: Optional[Path] = None, upload: bool = True) -> Dict[str, Path]:
    """
    Full publish: export the three parquet files locally, then (unless upload=False)
    upload them to R2. Returns {key: local_path}.
    """
    paths = export_all(out_dir=out_dir)
    if upload:
        upload_to_r2(paths)
    return paths
