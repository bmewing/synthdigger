"""
Local catalog store: a single DuckDB file (config.DUCKDB_PATH), no server required.

All timestamps are stored as naive UTC TIMESTAMPs - the same convention the
published parquet files use - so values round-trip between the local store and
the cloud read path without timezone gymnastics. Timezone-aware datetimes are
normalized to UTC by DuckDB on insert; naive datetimes are stored as given.

DuckDB is single-writer: only one process may hold a read-write connection to
the file at a time (concurrent read-only connections are fine). The pipeline is
a sequential CLI, so this only matters if you try to run two commands at once.
"""
import duckdb
import logging
from datetime import datetime, timezone
import numpy as np
from music_embeddings import config
from music_embeddings.version import SCHEMA_VERSION

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1280

# Naive-UTC "now" used for the last_synced_at/extracted_at bookkeeping columns.
SQL_UTC_NOW = "(now() AT TIME ZONE 'UTC')"


def get_connection(read_only: bool = False):
    """
    Opens and returns a connection to the DuckDB catalog file, creating the
    parent directory (and, in read-write mode, the file) if needed.
    """
    path = config.DUCKDB_PATH
    if read_only and not path.exists():
        raise FileNotFoundError(
            f"No catalog database at '{path}'. Run `python -m music_embeddings.database` "
            "to initialize it, then sync-plex/scan to populate it."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def init_db() -> None:
    """
    Initializes the catalog: the `embedding` schema and its four tables.
    Idempotent - safe to run on an existing database.
    """
    conn = get_connection()
    try:
        conn.execute("CREATE SCHEMA IF NOT EXISTS embedding;")

        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS embedding.track_embeddings (
            sha256 VARCHAR PRIMARY KEY,
            source_path TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            file_size BIGINT NOT NULL,
            file_mtime TIMESTAMP NOT NULL,
            audio_duration REAL NOT NULL,
            embedding_model_name VARCHAR NOT NULL,
            model_filename VARCHAR NOT NULL,
            embedding FLOAT[{EMBEDDING_DIM}] NOT NULL,
            extracted_at TIMESTAMP DEFAULT {SQL_UTC_NOW}
        );
        """)

        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS embedding.plex_artist_metadata (
            rating_key INTEGER PRIMARY KEY,
            artist_name VARCHAR NOT NULL,
            summary TEXT,
            genres VARCHAR[],
            styles VARCHAR[],
            moods VARCHAR[],
            added_at TIMESTAMP,
            last_synced_at TIMESTAMP DEFAULT {SQL_UTC_NOW}
        );
        """)

        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS embedding.plex_album_metadata (
            rating_key INTEGER PRIMARY KEY,
            artist_rating_key INTEGER,
            album_name VARCHAR NOT NULL,
            artist_name VARCHAR,
            year INTEGER,
            summary TEXT,
            genres VARCHAR[],
            styles VARCHAR[],
            moods VARCHAR[],
            added_at TIMESTAMP,
            last_synced_at TIMESTAMP DEFAULT {SQL_UTC_NOW}
        );
        """)

        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS embedding.plex_track_metadata (
            plex_rating_key INTEGER PRIMARY KEY,
            album_rating_key INTEGER,
            sha256 VARCHAR,
            play_count INTEGER DEFAULT 0,
            last_played_at TIMESTAMP,
            user_rating REAL,
            artist_name VARCHAR,
            album_name VARCHAR,
            track_title VARCHAR,
            genres VARCHAR[],
            moods VARCHAR[],
            added_to_plex_at TIMESTAMP,
            last_synced_at TIMESTAMP DEFAULT {SQL_UTC_NOW}
        );
        """)

        # Unified tall per-track label table. One row per (track, source, label):
        # holds discogs genres and the per-track AllMusic style/mood predictions in
        # a single flexible table that can absorb new label sources in future.
        # `source` is a spelled-out provenance string: 'discogs genre',
        # 'allmusic style', 'allmusic mood'.
        conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding.track_labels (
            sha256 VARCHAR,
            label VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            probability REAL NOT NULL,
            PRIMARY KEY (sha256, source, label)
        );
        """)

        # Key/value bookkeeping for the catalog itself. `schema_version` lets
        # `synthdigger version` tell a user whether their catalog matches the code and
        # whether upgrade steps are needed. Stamped once at creation; migrations
        # (not init_db) are responsible for advancing it later, so re-running
        # init_db on an existing catalog never changes a stamp that's already set.
        conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding.catalog_meta (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL
        );
        """)
        conn.execute(
            "INSERT INTO embedding.catalog_meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT (key) DO NOTHING;",
            (str(SCHEMA_VERSION),),
        )

        logger.info("Successfully initialized DuckDB catalog at %s", config.DUCKDB_PATH)
        print(f"Success: Initialized DuckDB catalog at '{config.DUCKDB_PATH}'.")

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        conn.close()


def get_schema_version() -> int | None:
    """
    Return the schema version stamped into the catalog.

    Returns None when no catalog file exists yet. A catalog that predates
    versioning (no `catalog_meta` table, or no `schema_version` row) is the
    original layout and reports as 1.
    """
    path = config.DUCKDB_PATH
    if not path.exists():
        return None
    conn = get_connection(read_only=True)
    try:
        row = conn.execute(
            "SELECT value FROM embedding.catalog_meta WHERE key = 'schema_version';"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 1
    except duckdb.Error:
        # catalog_meta doesn't exist -> pre-versioning catalog, i.e. the v1 baseline
        return 1
    finally:
        conn.close()


def check_schema_status() -> tuple[str, int | None, int]:
    """
    Compare the catalog's stamped schema version against what this build expects.

    Returns (status, current, expected) where status is one of:
      * 'no_catalog'    - no catalog file exists yet
      * 'ok'            - catalog matches this build
      * 'needs_upgrade' - catalog is older than this build (run upgrade steps)
      * 'code_outdated' - catalog is newer than this build (update SynthDigger)
    """
    expected = SCHEMA_VERSION
    current = get_schema_version()
    if current is None:
        return ("no_catalog", None, expected)
    if current < expected:
        return ("needs_upgrade", current, expected)
    if current > expected:
        return ("code_outdated", current, expected)
    return ("ok", current, expected)


def check_exists_by_hash(sha256: str) -> bool:
    """
    Checks if a track embedding hash already exists in the database.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM embedding.track_embeddings WHERE sha256 = ?;", (sha256,))
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"Database hash lookup failed for {sha256}: {e}")
        return False
    finally:
        conn.close()


def insert_embedding(
    sha256: str,
    source_path: str,
    source_filename: str,
    file_size: int,
    file_mtime: float,
    audio_duration: float,
    embedding_model_name: str,
    model_filename: str,
    embedding: np.ndarray
) -> None:
    """
    Inserts a track embedding and its metadata into the database.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Check if embedding already exists
            cur.execute("SELECT 1 FROM embedding.track_embeddings WHERE sha256 = ?;", (sha256,))
            if cur.fetchone() is not None:
                logger.info(f"Embedding for {sha256} already exists in database. Skipping insert.")
                return

            # Convert timestamp to UTC datetime (stored naive-UTC)
            mtime_dt = datetime.fromtimestamp(file_mtime, tz=timezone.utc)

            emb_list = np.asarray(embedding, dtype=np.float32).tolist()

            insert_query = """
            INSERT INTO embedding.track_embeddings (
                sha256, source_path, source_filename, file_size, file_mtime,
                audio_duration, embedding_model_name, model_filename, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """
            cur.execute(insert_query, (
                sha256, source_path, source_filename, file_size, mtime_dt,
                audio_duration, embedding_model_name, model_filename, emb_list
            ))
            logger.info(f"Successfully inserted embedding for '{source_filename}' into database.")
    except Exception as e:
        logger.error(f"Failed to insert embedding into database for '{source_filename}': {e}")
        raise
    finally:
        conn.close()


def insert_track_labels_batch(rows: list[tuple[str, str, str, float]]) -> None:
    """
    Insert a batch of (sha256, label, source, probability) tuples into
    embedding.track_labels. On conflict (same track, source, label) the
    probability is refreshed.
    """
    if not rows:
        return
    conn = get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO embedding.track_labels (sha256, label, source, probability)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (sha256, source, label) DO UPDATE SET probability = EXCLUDED.probability;
            """,
            rows,
        )
    except Exception as e:
        logger.error(f"Failed to insert batch of track labels: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    # Standard log configuration when run directly
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    init_db()
