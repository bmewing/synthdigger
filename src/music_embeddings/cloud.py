"""
Entry point helpers for the cloud Functions (functions/lib/music_embeddings is a
vendored copy of this package - see functions/README.md).

Functions are stateless per-invocation but a warm container can reuse a previous
invocation's Python module state, so the loaded ParquetDataSource (parquet fetched
from R2 + parsed into an in-memory numpy embedding matrix) is cached at module level:
the first (cold) invocation pays the fetch/parse cost, subsequent warm invocations
reuse it for free. Each deployed Function has its own container, so this cache is
per-function, not shared across e.g. `generate` and `seed-search`.

For local testing without any R2 setup, set LOCAL_PARQUET_DIR to a directory already
containing embeddings.parquet/tracks.parquet/labels.parquet (e.g. the output of
`python -m music_embeddings.cli publish --no-upload`) and the R2 fetch is skipped
entirely.
"""
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from music_embeddings import publish
from music_embeddings.datasource import ParquetDataSource

logger = logging.getLogger("music_embeddings.cloud")

_cached_datasource: Optional[ParquetDataSource] = None


def _request_origin(event: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(event, dict):
        return None
    headers = (event.get("http") or {}).get("headers") or {}
    return headers.get("origin") or headers.get("Origin")


def _cors_headers(event: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """
    Browsers reject `Access-Control-Allow-Origin: *` on any request that carries
    credentials (our session cookie), so a wildcard would silently break auth for
    every cross-origin call. Reflecting the actual request Origin back (standard
    pattern for credentialed CORS) works correctly whether the frontend ends up
    same-origin (production, once deployed under one App Platform domain/paths) or
    cross-origin (local dev, where the static files and Functions are served from
    different ports/hosts).
    """
    origin = _request_origin(event)
    return {
        "Access-Control-Allow-Origin": origin or "*",
        "Access-Control-Allow-Credentials": "true" if origin else "false",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Vary": "Origin",
    }


def json_response(body: Any, status: int = 200, event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Standard DO Functions web-response shape: JSON body + credential-safe CORS headers."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            **_cors_headers(event),
        },
        "body": json.dumps(body, default=str),
    }


def error_response(message: str, status: int = 400, event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return json_response({"error": message}, status=status, event=event)


def preflight_response(event: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Response for a CORS preflight OPTIONS request - no body, just the CORS headers."""
    return {"statusCode": 204, "headers": _cors_headers(event), "body": ""}


def is_preflight(event: Dict[str, Any]) -> bool:
    http = event.get("http", {}) if isinstance(event, dict) else {}
    return http.get("method") == "OPTIONS"


def _local_override_dir() -> Optional[Path]:
    override = os.environ.get("LOCAL_PARQUET_DIR")
    return Path(override) if override else None


def fetch_parquet(dest_dir: Optional[Path] = None, keys: Optional[List[str]] = None) -> Dict[str, Path]:
    """
    Returns local paths to the published parquet files, downloading them from R2
    first unless LOCAL_PARQUET_DIR is set. Reuses publish.py's key names/R2 client
    so there's a single source of truth for the object layout.

    `keys` restricts which files are fetched - pass just [TRACKS_KEY, LABELS_KEY]
    (a couple MB combined) to skip the ~50MB embeddings.parquet entirely for
    callers (like autocomplete-data) that never touch the embedding matrix.
    """
    keys = keys or [publish.EMBEDDINGS_KEY, publish.TRACKS_KEY, publish.LABELS_KEY]

    local_dir = _local_override_dir()
    if local_dir is not None:
        logger.info("LOCAL_PARQUET_DIR set - skipping R2 fetch, reading from %s", local_dir)
        return {key: local_dir / key for key in keys}

    dest_dir = Path(dest_dir) if dest_dir else Path(tempfile.gettempdir()) / "music-discovery-parquet"
    dest_dir.mkdir(parents=True, exist_ok=True)

    import urllib.request

    # Presigning is a local, no-network operation (boto3 just computes a signed
    # URL); the actual fetch goes through plain urllib rather than boto3's own S3
    # HTTP client. boto3's get_object()/download_file() both hung indefinitely on
    # the ~50MB embeddings file in DO's Functions sandbox (no error, no timeout -
    # small R2 objects worked fine, so it wasn't credentials/connectivity), while
    # urllib is already proven reliable here for multi-MB responses (DeepSeek/
    # OpenRouter). Switching the transport avoids whatever boto3-specific behavior
    # (connection pooling, chunked-transfer handling, etc.) was the actual cause.
    client = publish.get_r2_client()
    paths: Dict[str, Path] = {}
    for key in keys:
        dest_path = dest_dir / key
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": publish.config.R2_BUCKET, "Key": key}, ExpiresIn=300
        )
        with urllib.request.urlopen(url, timeout=30) as resp, open(dest_path, "wb") as f:
            f.write(resp.read())
        paths[key] = dest_path
        logger.info("Fetched r2://%s/%s -> %s", publish.config.R2_BUCKET, key, dest_path)

    return paths


def get_cached_datasource() -> ParquetDataSource:
    """Module-level cached ParquetDataSource, built on first call (cold start)."""
    global _cached_datasource
    if _cached_datasource is None:
        paths = fetch_parquet()
        _cached_datasource = ParquetDataSource(
            embeddings_path=paths[publish.EMBEDDINGS_KEY],
            tracks_path=paths[publish.TRACKS_KEY],
            labels_path=paths[publish.LABELS_KEY],
        )
        logger.info("ParquetDataSource loaded and cached for this container.")
    return _cached_datasource


_cached_autocomplete_data: Optional[Dict[str, Any]] = None


def get_cached_autocomplete_data() -> Dict[str, Any]:
    """
    Module-level cached {"songs": [...], "labels": [...]} for the frontend's
    typeahead fields, built on first call. Deliberately bypasses ParquetDataSource/
    get_cached_datasource entirely - those load the ~50MB embeddings.parquet into a
    numpy matrix, which is the actual cost behind seed-search/label-search's slow
    per-keystroke cold starts. This only ever touches tracks.parquet + labels.parquet
    (a couple MB combined), so the client can fetch it once on page load and filter
    everything locally afterward instead of hitting a Function per keystroke.

    Both lists are flat delimited strings rather than {key: value} objects: DO
    Functions caps a web action's response at 1MB, and at ~20k tracks the keyed-object
    form (repeating "artist"/"title" per record) came to ~1.2MB - over the cap, and
    the same opaque platform error the oversized cover-art response hit. Flat
    "Artist - Title" strings for songs and "source|label|track_count" for labels come
    to under 750KB for the same data - comfortably inside the cap with room for
    library growth - at the cost of the frontend parsing them back apart.
    """
    global _cached_autocomplete_data
    if _cached_autocomplete_data is None:
        import duckdb

        paths = fetch_parquet(keys=[publish.TRACKS_KEY, publish.LABELS_KEY])
        con = duckdb.connect(":memory:")
        con.execute("PRAGMA threads=1;")

        songs = con.execute(f"""
            SELECT artist_name, track_title
            FROM read_parquet('{paths[publish.TRACKS_KEY].as_posix()}')
            ORDER BY artist_name, track_title
        """).fetchall()

        labels = con.execute(f"""
            SELECT source, label, count(*) AS track_count
            FROM read_parquet('{paths[publish.LABELS_KEY].as_posix()}')
            GROUP BY source, label
            ORDER BY source, track_count DESC, label ASC
        """).fetchall()

        _cached_autocomplete_data = {
            "songs": [f"{r[0]} - {r[1]}" for r in songs],
            "labels": [f"{r[0]}|{r[1]}|{r[2]}" for r in labels],
        }
        logger.info(
            "Autocomplete data loaded and cached for this container (%d songs, %d labels).",
            len(songs), len(labels),
        )
    return _cached_autocomplete_data
