"""
Unified per-track labels (embedding.track_labels).

Consolidates every per-track label source into one flexible tall table:
    (sha256, label, source, probability)

``source`` is a spelled-out provenance string so the origin stays obvious:
    - 'discogs genre'  : the trimmed 400-class Discogs-EffNet genre predictions
    - 'allmusic style' : per-track AllMusic style predicted by the style tagger
    - 'allmusic mood'  : per-track AllMusic mood predicted by the curated mood tagger

New sources can be added later without a schema change.
"""

import logging
from pathlib import Path

from music_embeddings.database import get_connection, insert_track_labels_batch
from music_embeddings.genre_selection import select_genres, SelectionParams

logger = logging.getLogger("music_embeddings.labels")

SOURCE_DISCOGS_GENRE = "discogs genre"
SOURCE_ALLMUSIC_STYLE = "allmusic style"
SOURCE_ALLMUSIC_MOOD = "allmusic mood"

# tagger tag_type -> track_labels source string
TAG_TYPE_TO_SOURCE = {
    "style": SOURCE_ALLMUSIC_STYLE,
    "mood": SOURCE_ALLMUSIC_MOOD,
}

# Selection defaults for the taggers (tighter than the genre defaults because
# tagger probabilities saturate near 1.0). frac 0.85 / cap 5 keeps a clean handful.
TAGGER_SELECTION = SelectionParams(min_conf=0.10, frac=0.85, floor=0.05, cap=5)


def _copy_discogs_genres(cur) -> int:
    """
    Copy the (already trimmed) discogs_genre_predictions rows into track_labels.

    The legacy table is dropped once the one-time migration has run, so this is a
    no-op (returns -1) when it no longer exists -- letting migrate-labels still be
    used to refresh the style/mood sources.
    """
    cur.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'embedding' AND table_name = 'discogs_genre_predictions';"
    )
    if cur.fetchone()[0] == 0:
        return -1
    result = cur.execute(
        """
        INSERT INTO embedding.track_labels (sha256, label, source, probability)
        SELECT sha256, genre_style, ?, probability
        FROM embedding.discogs_genre_predictions
        ON CONFLICT (sha256, source, label) DO UPDATE SET probability = EXCLUDED.probability;
        """,
        (SOURCE_DISCOGS_GENRE,),
    ).fetchone()
    return int(result[0]) if result else 0


def _labels_from_parquet(parquet_path: Path, source: str, params: SelectionParams) -> list[tuple]:
    """Load a tagger OOF parquet, apply adaptive selection, return track_labels rows."""
    import pyarrow.parquet as pq
    from collections import defaultdict

    t = pq.read_table(str(parquet_path), columns=["sha256", "tag", "probability"]).to_pydict()
    by_track = defaultdict(list)
    for sha, tag, p in zip(t["sha256"], t["tag"], t["probability"]):
        by_track[sha].append((tag, float(p)))

    rows = []
    for sha, pairs in by_track.items():
        selected, _uncl = select_genres(
            pairs, min_conf=params.min_conf, frac=params.frac,
            floor=params.floor, cap=params.cap,
        )
        for label, prob in selected:
            rows.append((sha, label, source, prob))
    return rows


def migrate_to_track_labels(
    style_parquet: str,
    mood_parquet: str,
    params: SelectionParams = TAGGER_SELECTION,
    drop_old: bool = False,
) -> dict:
    """
    Populate embedding.track_labels from all three sources and (optionally)
    retire the old tables.

      1. copy the trimmed discogs genres           -> source 'discogs genre'
      2. adaptively select style tagger predictions -> source 'allmusic style'
      3. adaptively select mood tagger predictions  -> source 'allmusic mood'
      4. optionally DROP discogs_genre_predictions and track_tag_predictions

    Style/mood come from the honest out-of-fold parquets, trimmed with ``params``.
    Returns a stats dict.
    """
    stats = {}

    # 1. discogs genres (single SQL copy)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            n_genre = _copy_discogs_genres(cur)
    finally:
        conn.close()
    stats["discogs_genre_rows"] = n_genre
    if n_genre < 0:
        print("  discogs_genre_predictions already retired -> skipped genre copy")
    else:
        print(f"  copied {n_genre} discogs-genre rows -> track_labels")

    # 2 + 3. tagger predictions (adaptively trimmed)
    style_rows = _labels_from_parquet(Path(style_parquet), SOURCE_ALLMUSIC_STYLE, params)
    insert_track_labels_batch(style_rows)
    stats["allmusic_style_rows"] = len(style_rows)
    print(f"  inserted {len(style_rows)} allmusic-style rows (frac={params.frac}/cap={params.cap})")

    mood_rows = _labels_from_parquet(Path(mood_parquet), SOURCE_ALLMUSIC_MOOD, params)
    insert_track_labels_batch(mood_rows)
    stats["allmusic_mood_rows"] = len(mood_rows)
    print(f"  inserted {len(mood_rows)} allmusic-mood rows (frac={params.frac}/cap={params.cap})")

    # 4. verify + optional drop
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT source, count(*), count(DISTINCT sha256) FROM embedding.track_labels GROUP BY source ORDER BY source;")
            breakdown = cur.fetchall()
            print("  track_labels now holds:")
            for src, n, tracks in breakdown:
                print(f"     {src:<16} {n:>8} rows  across {tracks} tracks")
            stats["breakdown"] = {src: {"rows": n, "tracks": tracks} for src, n, tracks in breakdown}

            if drop_old:
                cur.execute("DROP TABLE IF EXISTS embedding.discogs_genre_predictions;")
                cur.execute("DROP TABLE IF EXISTS embedding.track_tag_predictions;")
                print("  dropped embedding.discogs_genre_predictions and embedding.track_tag_predictions")
                stats["dropped_old"] = True
    finally:
        conn.close()

    return stats
