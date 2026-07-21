"""
Pluggable read layer for playlist generation.

generate_playlist() and its helpers depend on five queries (eligible tracks, seed
search, label centroids, recent-activity centroid, label listing). This module
answers them via DuckDB SQL over two relations - `tracks` and `labels` - plus an
in-memory numpy embedding matrix, through two interchangeable sources:

- LocalDataSource   - views over the local DuckDB catalog file (config.DUCKDB_PATH),
  used by the CLI.
- ParquetDataSource - the same queries over tracks.parquet/labels.parquet published
  by publish.py (locally, or fetched from R2 into a local/temp path first), used by
  the read-only cloud app.

Both share _DuckDBQueries, so the local and cloud paths stay behaviorally identical
by construction.

Embeddings are handled specially: rather than asking DuckDB to join against the
embedding column per query, the whole embeddings table is loaded once into an
in-memory numpy matrix, and every query resolves sha256 -> row index against that
matrix. At ~21k tracks this is ~50MB and a few hundred ms, tiny compared to the
alternative.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union

import numpy as np

logger = logging.getLogger("music_embeddings.datasource")


class DataSource(Protocol):
    """Structural interface generate_playlist() depends on."""

    def get_eligible_tracks(
        self, ignore_play_history: bool = False, max_recency_months: int = 6, max_play_count: int = 2
    ) -> List[Dict[str, Any]]: ...

    def resolve_seed_songs(self, query: str) -> List[Dict[str, Any]]: ...

    def resolve_label_centroid(
        self, label_query: str, source: Optional[str] = None, min_prob: float = 0.1, limit: int = 150
    ) -> Tuple[Optional[np.ndarray], List[str]]: ...

    def resolve_recent_activity_centroid(
        self, days: int = 14, min_tracks: int = 3
    ) -> Tuple[Optional[np.ndarray], List[str]]: ...

    def list_available_labels(
        self, source: Optional[str] = None, filter_query: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]: ...


class _DuckDBQueries:
    """
    The five DataSource queries, written once against a DuckDB connection that
    exposes `tracks` (sha256, rating_key, artist_name, album_name, track_title,
    play_count, last_played_at) and `labels` (sha256, source, label, probability)
    views, plus an in-memory embedding matrix. Subclasses only differ in __init__.
    """

    con = None  # duckdb connection with tracks/labels views
    _emb_matrix: np.ndarray
    _sha_to_idx: Dict[str, int]

    def _load_embedding_matrix(self, emb_result: Dict[str, Any]) -> None:
        """Populate the sha -> matrix-row index from a fetchnumpy() result."""
        self._emb_shas: List[str] = emb_result['sha256'].tolist()
        self._emb_matrix = np.stack(emb_result['embedding']).astype(np.float32) if len(self._emb_shas) else np.zeros((0, 0), dtype=np.float32)
        self._sha_to_idx = {sha: i for i, sha in enumerate(self._emb_shas)}

    # -- helpers -----------------------------------------------------------

    def _row_to_track(self, r) -> Optional[Dict[str, Any]]:
        sha, rating_key, artist, album, title, play_count, last_played = r
        idx = self._sha_to_idx.get(sha)
        if idx is None:
            return None
        return {
            'sha256': sha,
            'rating_key': rating_key,
            'artist': artist or "Unknown Artist",
            'album': album or "Unknown Album",
            'title': title or "Untitled Track",
            'play_count': play_count or 0,
            'last_played': last_played,
            'embedding': self._emb_matrix[idx],
        }

    def _row_to_seed(self, r) -> Dict[str, Any]:
        sha, rating_key, artist, album, title = r
        return {
            'sha256': sha,
            'rating_key': rating_key,
            'artist': artist,
            'album': album,
            'title': title,
            'embedding': self._emb_matrix[self._sha_to_idx[sha]],
        }

    # -- DataSource interface ------------------------------------------------

    def get_eligible_tracks(self, ignore_play_history=False, max_recency_months=6, max_play_count=2):
        select = "SELECT sha256, rating_key, artist_name, album_name, track_title, play_count, last_played_at FROM tracks"
        if ignore_play_history:
            rows = self.con.execute(select).fetchall()
        else:
            rows = self.con.execute(f"""
                {select}
                WHERE (
                    last_played_at IS NULL
                    OR last_played_at < now() - INTERVAL '{int(max_recency_months)} months'
                    OR play_count <= {int(max_play_count)}
                )
            """).fetchall()

        tracks = [self._row_to_track(r) for r in rows]
        return [t for t in tracks if t is not None]

    def resolve_seed_songs(self, query: str) -> List[Dict[str, Any]]:
        query_str = query.strip()
        select = "SELECT sha256, rating_key, artist_name, album_name, track_title FROM tracks"

        if query_str.isdigit():
            rows = self.con.execute(f"{select} WHERE rating_key = ?", [int(query_str)]).fetchall()
            matches = [r for r in rows if r[0] in self._sha_to_idx]
            if matches:
                return [self._row_to_seed(matches[0])]

        if len(query_str) == 64 and all(c in '0123456789abcdefABCDEF' for c in query_str):
            rows = self.con.execute(f"{select} WHERE sha256 = ?", [query_str.lower()]).fetchall()
            matches = [r for r in rows if r[0] in self._sha_to_idx]
            if matches:
                return [self._row_to_seed(matches[0])]

        like_query = f"%{query_str}%"
        rows = self.con.execute(f"""
            {select}
            WHERE track_title ILIKE ?
               OR (artist_name || ' - ' || track_title) ILIKE ?
               OR artist_name ILIKE ?
            LIMIT 5
        """, [like_query, like_query, like_query]).fetchall()
        return [self._row_to_seed(r) for r in rows if r[0] in self._sha_to_idx]

    def resolve_label_centroid(self, label_query, source=None, min_prob=0.1, limit=150):
        from music_embeddings.playlist import _weighted_centroid

        if source:
            rows = self.con.execute("""
                SELECT sha256, label, probability FROM labels
                WHERE source = ? AND label ILIKE ? AND probability >= ?
                ORDER BY probability DESC LIMIT ?
            """, [source, f"%{label_query}%", min_prob, limit]).fetchall()
        else:
            rows = self.con.execute("""
                SELECT sha256, label, probability FROM labels
                WHERE label ILIKE ? AND probability >= ?
                ORDER BY probability DESC LIMIT ?
            """, [f"%{label_query}%", min_prob, limit]).fetchall()

        if not rows:
            return None, []

        matched_labels = list(set(r[1] for r in rows))
        sha_prob_map = {r[0]: r[2] for r in rows}
        emb_rows = [
            (sha, self._emb_matrix[self._sha_to_idx[sha]])
            for sha in sha_prob_map
            if sha in self._sha_to_idx
        ]
        return _weighted_centroid(emb_rows, sha_prob_map, matched_labels)

    def resolve_recent_activity_centroid(self, days=14, min_tracks=3):
        from music_embeddings.playlist import _unweighted_centroid

        days = max(1, int(days))
        rows = self.con.execute(f"""
            SELECT sha256 FROM tracks WHERE last_played_at >= now() - INTERVAL '{days} days'
        """).fetchall()
        shas = [r[0] for r in rows if r[0] in self._sha_to_idx]

        if len(shas) < min_tracks:
            return None, []

        emb_rows = [(sha, self._emb_matrix[self._sha_to_idx[sha]]) for sha in shas]
        return _unweighted_centroid(emb_rows)

    def list_available_labels(self, source=None, filter_query=None, limit=None):
        query_parts = ["SELECT source, label, count(*) as cnt, round(avg(probability), 3) as avg_prob FROM labels"]
        where_clauses = []
        params = []

        if source:
            where_clauses.append("source = ?")
            params.append(source)
        if filter_query and filter_query.strip():
            where_clauses.append("label ILIKE ?")
            params.append(f"%{filter_query.strip()}%")
        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))

        query_parts.append("GROUP BY source, label ORDER BY source, cnt DESC, label ASC")
        if limit:
            query_parts.append("LIMIT ?")
            params.append(limit)

        sql = " ".join(query_parts) + ";"
        rows = self.con.execute(sql, params).fetchall()
        return [{'source': r[0], 'label': r[1], 'track_count': r[2], 'avg_prob': float(r[3])} for r in rows]


class LocalDataSource(_DuckDBQueries):
    """
    DataSource over the local DuckDB catalog file. Opens the file read-only (so
    playlist generation can run alongside other readers) and exposes the two
    canonical views as TEMP views on this connection.
    """

    def __init__(self, db_path: Union[str, Path, None] = None):
        from music_embeddings import config

        path = Path(db_path) if db_path else config.DUCKDB_PATH
        if not path.exists():
            raise FileNotFoundError(
                f"No catalog database at '{path}'. Run sync-plex/scan first (see README)."
            )
        import duckdb
        self.con = duckdb.connect(str(path), read_only=True)

        self.con.execute("""
            CREATE TEMP VIEW tracks AS
            SELECT sha256, plex_rating_key AS rating_key, artist_name, album_name,
                   track_title, play_count, last_played_at
            FROM embedding.plex_track_metadata
            WHERE sha256 IS NOT NULL
        """)
        self.con.execute("""
            CREATE TEMP VIEW labels AS
            SELECT sha256, source, label, probability
            FROM embedding.track_labels
        """)

        emb_result = self.con.execute(
            "SELECT sha256, embedding FROM embedding.track_embeddings"
        ).fetchnumpy()
        self._load_embedding_matrix(emb_result)


class ParquetDataSource(_DuckDBQueries):
    """
    DataSource over the three published parquet files (see publish.py), for the
    cloud app - reading files fetched from R2 into a local/temp path first.
    """

    def __init__(
        self,
        embeddings_path: Union[str, Path],
        tracks_path: Union[str, Path],
        labels_path: Union[str, Path]
    ):
        import duckdb

        self.con = duckdb.connect(":memory:")
        # DuckDB defaults to spinning up a worker thread per detected CPU core for
        # parallel query execution. In a constrained/shared serverless sandbox this
        # thread pool can hang indefinitely waiting for scheduler time that never
        # comes, rather than erroring - pinning to a single thread avoids that class
        # of hang entirely, and at this data size (tens of thousands of rows) query
        # latency is dominated by I/O, not parallelism, so there's no real cost.
        self.con.execute("PRAGMA threads=1;")

        # Load embeddings via DuckDB's own parquet reader + fetchnumpy(), NOT pyarrow:
        # fetchnumpy() returns the fixed_size_list<float16> column as one small numpy
        # array per row (fast, no per-float Python object materialization), which
        # np.stack() turns into one contiguous float32 matrix. This is ~20x faster
        # than pyarrow's to_pylist() path (0.3s vs 6s+ for ~21k tracks) and avoids a
        # pyarrow runtime dependency, which would be too large to bundle into a
        # DigitalOcean Function (48MB package limit).
        embeddings_posix = Path(embeddings_path).as_posix()
        emb_result = self.con.execute(f"SELECT sha256, embedding FROM read_parquet('{embeddings_posix}')").fetchnumpy()
        self._load_embedding_matrix(emb_result)

        tracks_posix = Path(tracks_path).as_posix()
        labels_posix = Path(labels_path).as_posix()
        self.con.execute(f"CREATE VIEW tracks AS SELECT * FROM read_parquet('{tracks_posix}')")
        self.con.execute(f"CREATE VIEW labels AS SELECT * FROM read_parquet('{labels_posix}')")
