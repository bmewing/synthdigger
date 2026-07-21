"""
One-time migration: copy an existing Postgres catalog (the pre-DuckDB store this
project used) into the DuckDB file at DUCKDB_PATH.

Run this once if you had a working Postgres-based install before the project
switched to DuckDB; fresh installs never need it. Postgres connection settings
come from the same env vars/.env keys the old code used (DB_HOST, DB_PORT,
DB_NAME, DB_USER, DB_PASSWORD). Requires psycopg2-binary, which is no longer a
project dependency - install it just for this run:

    pip install psycopg2-binary
    python scripts/migrate_pg_to_duckdb.py

Timezone-aware Postgres timestamps are normalized to naive UTC by DuckDB on
insert, matching the new store's convention.
"""
import os
import sys

import numpy as np

try:
    import psycopg2
except ImportError:
    sys.exit("psycopg2 is required for this one-time migration: pip install psycopg2-binary")

from music_embeddings import config
from music_embeddings.database import get_connection, init_db

BATCH = 1000


def _parse_embedding(value) -> list[float]:
    """pgvector columns come back as '[0.1,0.2,...]' strings; real[] as lists."""
    if isinstance(value, str):
        return np.fromstring(value.strip().lstrip("[").rstrip("]"), sep=",", dtype=np.float32).tolist()
    return np.asarray(value, dtype=np.float32).tolist()


def _copy(pg_cur, duck, select_sql: str, insert_sql: str, transform=None, label: str = "") -> int:
    pg_cur.execute(select_sql)
    total = 0
    while True:
        rows = pg_cur.fetchmany(BATCH)
        if not rows:
            break
        if transform:
            rows = [transform(r) for r in rows]
        duck.executemany(insert_sql, rows)
        total += len(rows)
        print(f"  {label}: {total} rows...", end="\r")
    print(f"  {label}: {total} rows    ")
    return total


def main():
    if config.DUCKDB_PATH.exists():
        sys.exit(
            f"Refusing to migrate into an existing DuckDB file: {config.DUCKDB_PATH}\n"
            "Move it aside first if you really want to re-run the migration."
        )

    pg = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ.get("DB_NAME", "plex_music"),
        user=os.environ.get("DB_USER", "plex_analysis"),
        password=os.environ.get("DB_PASSWORD"),
    )

    init_db()
    duck = get_connection()
    pg_cur = pg.cursor()
    try:
        _copy(
            pg_cur, duck,
            "SELECT sha256, source_path, source_filename, file_size, file_mtime, audio_duration, "
            "embedding_model_name, model_filename, embedding FROM embedding.track_embeddings;",
            "INSERT OR IGNORE INTO embedding.track_embeddings (sha256, source_path, source_filename, "
            "file_size, file_mtime, audio_duration, embedding_model_name, model_filename, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            transform=lambda r: (*r[:8], _parse_embedding(r[8])),
            label="track_embeddings",
        )
        _copy(
            pg_cur, duck,
            "SELECT rating_key, artist_name, summary, genres, styles, moods, added_at "
            "FROM embedding.plex_artist_metadata;",
            "INSERT OR IGNORE INTO embedding.plex_artist_metadata (rating_key, artist_name, summary, "
            "genres, styles, moods, added_at) VALUES (?, ?, ?, ?, ?, ?, ?);",
            label="plex_artist_metadata",
        )
        _copy(
            pg_cur, duck,
            "SELECT rating_key, artist_rating_key, album_name, artist_name, year, summary, genres, "
            "styles, moods, added_at FROM embedding.plex_album_metadata;",
            "INSERT OR IGNORE INTO embedding.plex_album_metadata (rating_key, artist_rating_key, "
            "album_name, artist_name, year, summary, genres, styles, moods, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            label="plex_album_metadata",
        )
        _copy(
            pg_cur, duck,
            "SELECT plex_rating_key, album_rating_key, sha256, play_count, last_played_at, user_rating, "
            "artist_name, album_name, track_title, genres, moods, added_to_plex_at "
            "FROM embedding.plex_track_metadata;",
            "INSERT OR IGNORE INTO embedding.plex_track_metadata (plex_rating_key, album_rating_key, "
            "sha256, play_count, last_played_at, user_rating, artist_name, album_name, track_title, "
            "genres, moods, added_to_plex_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            label="plex_track_metadata",
        )
        _copy(
            pg_cur, duck,
            "SELECT sha256, label, source, probability FROM embedding.track_labels;",
            "INSERT OR IGNORE INTO embedding.track_labels (sha256, label, source, probability) "
            "VALUES (?, ?, ?, ?);",
            label="track_labels",
        )
    finally:
        pg_cur.close()
        pg.close()
        duck.close()

    print(f"\nDone. DuckDB catalog written to {config.DUCKDB_PATH}")
    print("Spot-check with e.g.:")
    print("  python -c \"import duckdb; con = duckdb.connect(r'" + str(config.DUCKDB_PATH) + "', read_only=True); "
          "print(con.execute('SELECT count(*) FROM embedding.track_embeddings').fetchall())\"")


if __name__ == "__main__":
    main()
