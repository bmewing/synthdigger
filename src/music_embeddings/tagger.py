"""
Weakly-supervised per-track style/mood tagger.

Problem
-------
Plex/AllMusic curates ``styles`` and ``moods`` at the *artist* and *album*
level, not per track. We already have a frozen 1280-dim Discogs-EffNet audio
embedding for every track (``embedding.track_embeddings``). This module learns
to push those coarse bag-level tags down to individual tracks.

Approach (multi-instance / weak supervision)
--------------------------------------------
Treat each album as a "bag": every track inherits the union of its album's and
artist's tags as a *noisy* multi-label target. We then fit a **per-tag linear
probe** -- a One-vs-Rest logistic regression on the (standardized) embedding --
one binary classifier per tag.

Why a linear probe rather than a deep head:
  * The EffNet embedding space is already near-linearly separable by
    genre/style (that is what it was pretrained for), so a linear model is a
    strong baseline and the community-standard way to evaluate frozen audio
    embeddings.
  * Logistic regression emits a calibrated per-tag probability in [0, 1].
  * A linear model is far more robust to the label noise we deliberately
    introduce by blanket-inheriting album tags -- it cannot memorize
    per-example noise the way an over-parameterized net can.
  * Each learned tag is a direction in embedding space; the decision score is a
    dot product, so tracks that acoustically match a tag are "pulled" up in
    probability even when their album tag was wrong or missing.

The estimator is intentionally swappable (see ``TrackTagger.build_estimator``)
if we later want to trade the linear head for a small MLP.

Evaluation must be **grouped by artist** (``GroupKFold`` / ``GroupShuffleSplit``)
so an artist's tracks never straddle train/test -- otherwise the model can cheat
by memorizing artist identity and the metrics lie.

NOTE: This module is scaffolding. ``report_label_coverage`` and ``init_db`` are
safe to run against a partially-populated database; ``train_tagger`` should wait
until the Plex taxonomy sync has finished.
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from music_embeddings import config
from music_embeddings.database import get_connection

logger = logging.getLogger("music_embeddings.tagger")

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

TAG_TYPES = ("style", "mood")

# A tag needs at least this many positive tracks (after inheritance) before we
# bother training a classifier for it. Rare tags produce degenerate models.
DEFAULT_MIN_SUPPORT = 50

# Where trained tagger artifacts live (one per tag_type).
MODEL_DIR = Path(config.MODEL_PATH).parent / "taggers"

# Current artifact/version tag stamped onto stored predictions.
MODEL_VERSION = "v1"

# When storing predictions we drop near-zero probabilities to keep the tall
# table from exploding to n_tracks * n_tags rows.
DEFAULT_MIN_STORE_PROB = 0.10


# --------------------------------------------------------------------------- #
# Dataset container
# --------------------------------------------------------------------------- #

@dataclass
class TaggingDataset:
    """Assembled training data for one tag_type."""
    tag_type: str
    sha256: list[str]                       # length n
    X: np.ndarray                           # (n, 1280) float32
    Y: np.ndarray                           # (n, k) uint8 multi-hot
    groups: np.ndarray                      # (n,) artist group id (int)
    tags: list[str]                         # length k, column order of Y
    dropped_tags: dict[str, int] = field(default_factory=dict)  # tag -> support, below threshold

    @property
    def n_tracks(self) -> int:
        return len(self.sha256)

    @property
    def n_tags(self) -> int:
        return len(self.tags)


# --------------------------------------------------------------------------- #
# Embedding parsing
# --------------------------------------------------------------------------- #

def _parse_embedding(value) -> np.ndarray:
    """
    Normalize a stored embedding into a float32 vector.

    DuckDB returns FLOAT[1280] array columns as tuples; legacy stores/exports may
    hand us strings like '[0.1,0.2,...]' or Python lists. Handle all of them.
    """
    if isinstance(value, str):
        return np.fromstring(value.strip().lstrip("[").rstrip("]"), sep=",", dtype=np.float32)
    return np.asarray(value, dtype=np.float32)


# --------------------------------------------------------------------------- #
# Label inheritance query
# --------------------------------------------------------------------------- #

def _label_query(tag_type: str, include_artist_moods: bool = True) -> str:
    """
    Build the SQL that joins each embedded track to the union of its album's and
    artist's tags of the requested type. For moods we also fold in any track-level
    moods (tracks expose ``moods`` but not ``styles`` in Plex's data model).

    ``include_artist_moods`` (mood only): when False, artist-level moods are
    dropped and labels come only from track + album moods. Artist moods are the
    noisiest source -- they blanket every track an artist ever made -- so
    excluding them removes ~2.6k tracks whose only mood signal is artist identity
    and tightens the remaining labels to album resolution.

    Returns rows of: (sha256, embedding, group_id, tags[])
    Only rows with at least one inherited tag are returned.
    """
    if tag_type not in TAG_TYPES:
        raise ValueError(f"tag_type must be one of {TAG_TYPES}, got {tag_type!r}")

    if tag_type == "style":
        # tracks have no styles column -> album styles UNION artist styles
        tag_expr = "COALESCE(al.styles, []) || COALESCE(ar.styles, [])"
        nonempty = "(COALESCE(len(al.styles),0) + COALESCE(len(ar.styles),0)) > 0"
    elif include_artist_moods:  # mood, all sources
        tag_expr = "COALESCE(t.moods, []) || COALESCE(al.moods, []) || COALESCE(ar.moods, [])"
        nonempty = ("(COALESCE(len(t.moods),0) + COALESCE(len(al.moods),0) "
                    "+ COALESCE(len(ar.moods),0)) > 0")
    else:  # mood, track + album only (drop noisy artist-level moods)
        tag_expr = "COALESCE(t.moods, []) || COALESCE(al.moods, [])"
        nonempty = ("(COALESCE(len(t.moods),0) + COALESCE(len(al.moods),0)) > 0")

    return f"""
        SELECT
            e.sha256,
            e.embedding,
            COALESCE(al.artist_rating_key, -1) AS group_id,
            ({tag_expr}) AS tags
        FROM embedding.track_embeddings e
        JOIN embedding.plex_track_metadata t ON t.sha256 = e.sha256
        LEFT JOIN embedding.plex_album_metadata al ON al.rating_key = t.album_rating_key
        LEFT JOIN embedding.plex_artist_metadata ar ON ar.rating_key = al.artist_rating_key
        WHERE {nonempty};
    """


# --------------------------------------------------------------------------- #
# Pure label-matrix assembly (DB-independent, unit-testable)
# --------------------------------------------------------------------------- #

def assemble_label_matrix(
    rows: list[tuple],
    tag_type: str,
    min_support: int = DEFAULT_MIN_SUPPORT,
    tag_whitelist: set[str] | None = None,
) -> TaggingDataset:
    """
    Turn raw ``(sha256, embedding, group_id, tags)`` rows into a TaggingDataset.

    A tag is kept only if at least ``min_support`` tracks carry it (after
    inheritance and de-duplication per track). Tracks that end up with no kept
    tags are still retained as all-negative rows -- they are legitimate negatives
    for the surviving tags.

    ``tag_whitelist``: if given, only tags in this set are eligible (still subject
    to ``min_support``). Used to scope the mood model down to the curated,
    audio-learnable subset. Because OvR trains each tag independently, whitelisting
    yields the same per-tag classifiers as the full model -- it just drops the
    tags that carry no reliable audio signal.

    This function is deliberately free of any DB dependency so it can be tested
    with synthetic rows.
    """
    # First pass: per-track de-duplicated tag sets + support counts.
    track_tags: list[set[str]] = []
    support: dict[str, int] = {}
    for _sha, _emb, _grp, tags in rows:
        tset = {tg for tg in (tags or []) if tg}
        track_tags.append(tset)
        for tg in tset:
            support[tg] = support.get(tg, 0) + 1

    eligible = support if tag_whitelist is None else {t: c for t, c in support.items() if t in tag_whitelist}
    kept = sorted(tg for tg, c in eligible.items() if c >= min_support)
    dropped = {tg: c for tg, c in eligible.items() if c < min_support}
    tag_index = {tg: i for i, tg in enumerate(kept)}

    n, k = len(rows), len(kept)
    # Infer embedding dim from the first row (falls back to 1280 for empty input).
    dim = _parse_embedding(rows[0][1]).shape[0] if n else 1280

    X = np.empty((n, dim), dtype=np.float32)
    Y = np.zeros((n, k), dtype=np.uint8)
    groups = np.empty(n, dtype=np.int64)
    sha_list: list[str] = []

    for i, ((sha, emb, grp, _tags), tset) in enumerate(zip(rows, track_tags)):
        X[i] = _parse_embedding(emb)
        groups[i] = int(grp) if grp is not None else -1
        sha_list.append(sha)
        for tg in tset:
            j = tag_index.get(tg)
            if j is not None:
                Y[i, j] = 1

    return TaggingDataset(
        tag_type=tag_type,
        sha256=sha_list,
        X=X,
        Y=Y,
        groups=groups,
        tags=kept,
        dropped_tags=dropped,
    )


def build_label_matrix(
    tag_type: str,
    min_support: int = DEFAULT_MIN_SUPPORT,
    include_artist_moods: bool = True,
    tag_whitelist: set[str] | None = None,
) -> TaggingDataset:
    """Fetch inherited weak labels from the DB and assemble a TaggingDataset."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_label_query(tag_type, include_artist_moods=include_artist_moods))
            rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Fetched %d weakly-labeled tracks for tag_type=%s", len(rows), tag_type)
    return assemble_label_matrix(rows, tag_type, min_support=min_support, tag_whitelist=tag_whitelist)


# --------------------------------------------------------------------------- #
# Read-only coverage report (safe first step; runnable on partial data)
# --------------------------------------------------------------------------- #

def report_label_coverage(min_support: int = DEFAULT_MIN_SUPPORT, top_n: int = 25) -> None:
    """
    Print label-coverage statistics for both tag types. Read-only; safe to run
    while the Plex taxonomy sync is still populating. Useful for choosing a
    sensible ``min_support`` before training.
    """
    for tag_type in TAG_TYPES:
        ds = build_label_matrix(tag_type, min_support=min_support)
        print(f"\n=== {tag_type.upper()} ===")
        print(f"tracks with >=1 inherited {tag_type}: {ds.n_tracks}")
        print(f"tags kept (support >= {min_support}): {ds.n_tags}")
        print(f"tags dropped (below threshold):    {len(ds.dropped_tags)}")

        if ds.n_tracks and ds.n_tags:
            per_track = ds.Y.sum(axis=1)
            covered = int((per_track > 0).sum())
            print(f"tracks with >=1 KEPT tag:          {covered} "
                  f"({100.0 * covered / ds.n_tracks:.1f}%)")
            print(f"mean kept tags / track:            {per_track.mean():.2f}")

            supports = ds.Y.sum(axis=0)
            order = np.argsort(supports)[::-1][:top_n]
            print(f"top {min(top_n, ds.n_tags)} tags by support:")
            for j in order:
                print(f"    {ds.tags[j]:<32} {int(supports[j])}")


# --------------------------------------------------------------------------- #
# The model: a swappable per-tag linear probe
# --------------------------------------------------------------------------- #

class TrackTagger:
    """
    One-vs-Rest linear-probe multi-label tagger over frozen embeddings.

    Wraps an sklearn estimator plus the tag vocabulary and knows how to persist
    itself. ``predict_proba`` returns an (n, k) matrix of per-tag probabilities
    aligned to ``self.tags``.
    """

    def __init__(self, tag_type: str, tags: list[str], estimator=None,
                 model_version: str = MODEL_VERSION, metrics: dict | None = None):
        self.tag_type = tag_type
        self.tags = tags
        self.estimator = estimator
        self.model_version = model_version
        self.metrics = metrics or {}

    @staticmethod
    def build_estimator(C: float = 1.0, max_iter: int = 1000):
        """
        Construct the untrained OvR linear probe.

        StandardScaler helps logistic regression converge on the raw embedding
        dims; ``class_weight='balanced'`` counteracts the heavy tag imbalance;
        OvR fits one independent binary head per tag (true multi-label, tags are
        not mutually exclusive).

        Structure matters: the StandardScaler sits *outside* the OvR so it is fit
        exactly once on the full matrix. Nesting it inside OvR would clone and
        refit the scaler once per tag (hundreds of redundant passes over the same
        18k x 1280 data) for an identical transform.

        Swap the LogisticRegression here for an MLPClassifier or a small torch
        head later without touching the rest of the pipeline.
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.multiclass import OneVsRestClassifier
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        ovr = OneVsRestClassifier(
            LogisticRegression(
                C=C,
                max_iter=max_iter,
                class_weight="balanced",
                solver="liblinear",
            ),
            n_jobs=-1,
        )
        return make_pipeline(StandardScaler(), ovr)

    def fit(self, X: np.ndarray, Y: np.ndarray) -> "TrackTagger":
        if self.estimator is None:
            self.estimator = self.build_estimator()
        self.estimator.fit(X, Y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return (n_samples, n_tags) probabilities aligned to self.tags."""
        proba = self.estimator.predict_proba(X)
        # OneVsRestClassifier returns an (n, k) array for multilabel Y already.
        return np.asarray(proba, dtype=np.float32)

    # -- persistence -------------------------------------------------------- #

    def save(self, path: Path) -> None:
        import joblib
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "tag_type": self.tag_type,
                "tags": self.tags,
                "estimator": self.estimator,
                "model_version": self.model_version,
                "metrics": self.metrics,
            },
            path,
        )
        logger.info("Saved %s tagger -> %s", self.tag_type, path)

    @classmethod
    def load(cls, path: Path) -> "TrackTagger":
        import joblib
        blob = joblib.load(path)
        return cls(
            tag_type=blob["tag_type"],
            tags=blob["tags"],
            estimator=blob["estimator"],
            model_version=blob.get("model_version", MODEL_VERSION),
            metrics=blob.get("metrics", {}),
        )


def model_path_for(tag_type: str) -> Path:
    return MODEL_DIR / f"tagger_{tag_type}.joblib"


# --------------------------------------------------------------------------- #
# Training (do not run until the taxonomy sync has finished)
# --------------------------------------------------------------------------- #

def train_tagger(
    tag_type: str,
    min_support: int = DEFAULT_MIN_SUPPORT,
    C: float = 1.0,
    test_size: float = 0.2,
    random_state: int = 42,
    include_artist_moods: bool = True,
    tag_whitelist: set[str] | None = None,
) -> TrackTagger:
    """
    Build the weak-label dataset, evaluate with an artist-grouped holdout, then
    refit on all data and persist the artifact.

    Evaluation uses average precision (area under PR curve) per tag, which is the
    right metric for rare, imbalanced multi-label targets. Splitting is grouped
    by artist so no artist appears in both train and test.

    ``include_artist_moods`` is forwarded to the label query (mood only); set
    False to train on the tighter track+album mood labels. ``tag_whitelist``
    scopes the model to a curated tag subset (e.g. the audio-learnable moods).
    """
    from sklearn.metrics import average_precision_score
    from sklearn.model_selection import GroupShuffleSplit

    ds = build_label_matrix(tag_type, min_support=min_support,
                            include_artist_moods=include_artist_moods,
                            tag_whitelist=tag_whitelist)
    if ds.n_tracks == 0 or ds.n_tags == 0:
        raise RuntimeError(
            f"No trainable data for tag_type={tag_type} "
            f"(tracks={ds.n_tracks}, tags={ds.n_tags}). "
            "Has the Plex taxonomy sync populated album/artist tags yet?"
        )

    logger.info("Training %s tagger: %d tracks x %d tags", tag_type, ds.n_tracks, ds.n_tags)

    # Artist-grouped holdout for honest metrics.
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_idx, test_idx = next(splitter.split(ds.X, ds.Y, groups=ds.groups))

    tagger = TrackTagger(tag_type, ds.tags, estimator=TrackTagger.build_estimator(C=C))
    tagger.fit(ds.X[train_idx], ds.Y[train_idx])

    proba = tagger.predict_proba(ds.X[test_idx])
    y_true = ds.Y[test_idx]

    # Per-tag AP over tags that have at least one positive in the test fold.
    # Also record each tag's test-set prevalence -- AP's random baseline equals
    # prevalence, so "lift over chance" is the honest way to read these numbers.
    per_tag = []  # (tag, ap, prevalence, support_in_test)
    for j in range(ds.n_tags):
        pos = int(y_true[:, j].sum())
        if pos > 0:
            ap = average_precision_score(y_true[:, j], proba[:, j])
            per_tag.append((ds.tags[j], float(ap), pos / len(test_idx), pos))

    aps = np.array([p[1] for p in per_tag]) if per_tag else np.array([])
    prevs = np.array([p[2] for p in per_tag]) if per_tag else np.array([])
    weights = np.array([p[3] for p in per_tag], dtype=float) if per_tag else np.array([])

    macro_ap = float(aps.mean()) if len(aps) else float("nan")
    weighted_ap = float(np.average(aps, weights=weights)) if len(aps) else float("nan")
    # Micro AP: pool all (track, tag) decisions together (dominated by common tags).
    eval_cols = [ds.tags.index(t[0]) for t in per_tag]
    micro_ap = (float(average_precision_score(y_true[:, eval_cols].ravel(), proba[:, eval_cols].ravel()))
                if eval_cols else float("nan"))
    mean_lift = float(np.mean(aps / prevs)) if len(aps) else float("nan")

    metrics = {
        "macro_average_precision": macro_ap,
        "weighted_average_precision": weighted_ap,
        "micro_average_precision": micro_ap,
        "mean_lift_over_chance": mean_lift,
        "n_eval_tags": len(per_tag),
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx)),
        "min_support": min_support,
    }
    logger.info("Holdout macro-AP=%.4f weighted-AP=%.4f micro-AP=%.4f lift=%.1fx",
                macro_ap, weighted_ap, micro_ap, mean_lift)
    print(f"[{tag_type}] holdout AP  macro={macro_ap:.4f}  weighted={weighted_ap:.4f}  "
          f"micro={micro_ap:.4f}  mean-lift-over-chance={mean_lift:.1f}x  "
          f"(train={len(train_idx)}, test={len(test_idx)}, tags={len(per_tag)})")

    # Best/worst tags by AP for a quick eyeball of where the signal is.
    per_tag_sorted = sorted(per_tag, key=lambda t: t[1], reverse=True)
    print(f"[{tag_type}] best tags (AP | prevalence | support):")
    for tag, ap, prev, sup in per_tag_sorted[:8]:
        print(f"    {tag:<32} AP={ap:.3f}  prev={prev:.3f}  n={sup}")
    print(f"[{tag_type}] worst tags:")
    for tag, ap, prev, sup in per_tag_sorted[-5:]:
        print(f"    {tag:<32} AP={ap:.3f}  prev={prev:.3f}  n={sup}")

    # Refit on ALL data for the deployed artifact.
    final = TrackTagger(tag_type, ds.tags, estimator=TrackTagger.build_estimator(C=C),
                        metrics=metrics)
    final.fit(ds.X, ds.Y)
    final.save(model_path_for(tag_type))
    return final


# --------------------------------------------------------------------------- #
# Out-of-fold prediction (honest per-track scores for validation)
# --------------------------------------------------------------------------- #

def out_of_fold_proba(ds: TaggingDataset, n_splits: int = 5, C: float = 1.0) -> np.ndarray:
    """
    Compute honest (n_tracks, n_tags) probabilities where every track is scored
    by a model trained only on OTHER artists' tracks. Uses GroupKFold on the
    artist groups so no artist leaks across the fold boundary -- this removes the
    in-sample optimism of scoring tracks the deployed model trained on.
    """
    from sklearn.model_selection import GroupKFold

    gkf = GroupKFold(n_splits=n_splits)
    oof = np.zeros((ds.n_tracks, ds.n_tags), dtype=np.float32)
    for fold, (tr, te) in enumerate(gkf.split(ds.X, ds.Y, groups=ds.groups), 1):
        clf = TrackTagger(ds.tag_type, ds.tags, estimator=TrackTagger.build_estimator(C=C))
        clf.fit(ds.X[tr], ds.Y[tr])
        oof[te] = clf.predict_proba(ds.X[te])
        logger.info("OOF %s fold %d/%d done (%d test tracks)", ds.tag_type, fold, n_splits, len(te))
    return oof


def export_out_of_fold_parquet(
    tag_type: str,
    out_path: Path,
    n_splits: int = 5,
    C: float = 1.0,
    min_store_prob: float = DEFAULT_MIN_STORE_PROB,
    include_artist_moods: bool = True,
    tag_whitelist: set[str] | None = None,
) -> Path:
    """
    Build the weak-label dataset, compute out-of-fold probabilities, and write
    them (long format, with artist/album/title for eyeballing) to Parquet. These
    are the honest scores to validate before any DB write.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    ds = build_label_matrix(tag_type, include_artist_moods=include_artist_moods,
                            tag_whitelist=tag_whitelist)
    logger.info("OOF dataset %s: %d tracks x %d tags", tag_type, ds.n_tracks, ds.n_tags)
    oof = out_of_fold_proba(ds, n_splits=n_splits, C=C)

    # Metadata for readability.
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT sha256, artist_name, album_name, track_title "
                        "FROM embedding.plex_track_metadata;")
            meta = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    finally:
        conn.close()

    col_sha, col_artist, col_album, col_title, col_tag, col_prob = [], [], [], [], [], []
    for i, sha in enumerate(ds.sha256):
        artist, album, title = meta.get(sha, (None, None, None))
        row = oof[i]
        for j, p in enumerate(row):
            if p >= min_store_prob:
                col_sha.append(sha); col_artist.append(artist)
                col_album.append(album); col_title.append(title)
                col_tag.append(ds.tags[j]); col_prob.append(float(p))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({
        "sha256": col_sha,
        "artist_name": col_artist,
        "album_name": col_album,
        "track_title": col_title,
        "tag_type": [tag_type] * len(col_sha),
        "tag": col_tag,
        "probability": pa.array(col_prob, type=pa.float32()),
        "model_version": [f"{MODEL_VERSION}-oof{n_splits}"] * len(col_sha),
    })
    pq.write_table(table, out_path)
    print(f"[{tag_type}] OOF: scored {ds.n_tracks} tracks x {ds.n_tags} tags, "
          f"wrote {len(col_sha)} rows (prob >= {min_store_prob}) -> {out_path}")
    return out_path


# --------------------------------------------------------------------------- #
# Inference -> tall predictions table
# --------------------------------------------------------------------------- #

_tagger_cache: dict[str, "TrackTagger"] = {}


def get_tagger(tag_type: str) -> "TrackTagger":
    """Load-and-cache the trained tagger for `tag_type` (process-lifetime cache)."""
    if tag_type not in _tagger_cache:
        _tagger_cache[tag_type] = TrackTagger.load(model_path_for(tag_type))
    return _tagger_cache[tag_type]


def predict_track_labels(
    sha256: str,
    embedding: np.ndarray,
    tag_type: str,
    params=None,
) -> list[tuple[str, str, str, float]]:
    """
    Score one already-computed embedding with the trained `tag_type` tagger and
    return adaptively-selected track_labels rows (sha256, label, source, probability).

    For tagging a track as it's ingested: no DB query, no catalog scan, just a
    single (1, 1280) predict_proba call against the cached model. This is the
    incremental counterpart to predict_and_store, which re-scores the entire
    catalog and is meant for periodic full re-review/backfill instead.
    """
    from music_embeddings.labels import TAG_TYPE_TO_SOURCE, TAGGER_SELECTION
    from music_embeddings.genre_selection import select_genres

    params = params or TAGGER_SELECTION
    source = TAG_TYPE_TO_SOURCE[tag_type]
    tagger = get_tagger(tag_type)

    proba = tagger.predict_proba(embedding.reshape(1, -1))[0]
    selected, _uncl = select_genres(
        zip(tagger.tags, proba), min_conf=params.min_conf, frac=params.frac,
        floor=params.floor, cap=params.cap,
    )
    return [(sha256, label, source, float(p)) for label, p in selected]


def predict_and_store(
    tag_type: str,
    params=None,
    batch_size: int = 512,
) -> None:
    """
    Score every embedded track with the trained tagger, adaptively select each
    track's labels (see genre_selection), and upsert them into the unified
    embedding.track_labels table with the appropriate source
    ('allmusic style' / 'allmusic mood').

    This is the going-forward path (e.g. for newly added tracks). It scores with
    the deployed all-data model; note those scores are optimistic for tracks the
    model trained on -- the honest catalog-wide backfill uses the out-of-fold
    parquets via labels.migrate_to_track_labels.
    """
    from music_embeddings.labels import TAG_TYPE_TO_SOURCE, TAGGER_SELECTION
    from music_embeddings.database import insert_track_labels_batch

    params = params or TAGGER_SELECTION
    source = TAG_TYPE_TO_SOURCE[tag_type]

    path = model_path_for(tag_type)
    if not path.exists():
        raise FileNotFoundError(
            f"No trained {tag_type} tagger at '{path}'. Run train-tagger first."
        )
    tagger = TrackTagger.load(path)
    tags = tagger.tags

    conn = get_connection()
    total_tracks = 0
    total_rows = 0
    try:
        # Stream embeddings in fetchmany() batches instead of loading 20k*1280 at once.
        with conn.cursor() as cur:
            cur.execute("SELECT sha256, embedding FROM embedding.track_embeddings;")
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                batch = [(sha256, _parse_embedding(emb)) for sha256, emb in rows]
                total_rows += _flush_batch(tagger, tags, batch, source, params, insert_track_labels_batch)
                total_tracks += len(batch)
    finally:
        conn.close()

    print(f"[{tag_type}] scored {total_tracks} tracks, wrote {total_rows} '{source}' label rows "
          f"(frac={params.frac}/cap={params.cap}).")


def predict_to_parquet(
    tag_type: str,
    out_path: Path | None = None,
    min_store_prob: float = DEFAULT_MIN_STORE_PROB,
    batch_size: int = 512,
) -> Path:
    """
    Score every embedded track with the trained tagger and write per-tag
    probabilities to a Parquet file (long format) instead of the database, so
    results can be validated before committing them.

    The export joins in artist/album/track titles for human sanity-checking.
    Columns: sha256, artist_name, album_name, track_title, tag_type, tag,
    probability, model_version.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = model_path_for(tag_type)
    if not path.exists():
        raise FileNotFoundError(
            f"No trained {tag_type} tagger at '{path}'. Run train-tagger first."
        )
    tagger = TrackTagger.load(path)
    tags = tagger.tags

    if out_path is None:
        out_path = MODEL_DIR / f"predictions_{tag_type}.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Accumulate long-format columns.
    col_sha, col_artist, col_album, col_title = [], [], [], []
    col_tag, col_prob = [], []

    conn = get_connection()
    total_tracks = 0
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.sha256, e.embedding, t.artist_name, t.album_name, t.track_title
                FROM embedding.track_embeddings e
                LEFT JOIN embedding.plex_track_metadata t ON t.sha256 = e.sha256;
            """)
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                batch = [(sha256, _parse_embedding(emb), artist, album, title)
                         for sha256, emb, artist, album, title in rows]
                total_tracks += _accumulate_parquet_batch(
                    tagger, tags, batch, min_store_prob,
                    col_sha, col_artist, col_album, col_title, col_tag, col_prob)
    finally:
        conn.close()

    table = pa.table({
        "sha256": col_sha,
        "artist_name": col_artist,
        "album_name": col_album,
        "track_title": col_title,
        "tag_type": [tag_type] * len(col_sha),
        "tag": col_tag,
        "probability": pa.array(col_prob, type=pa.float32()),
        "model_version": [tagger.model_version] * len(col_sha),
    })
    pq.write_table(table, out_path)

    print(f"[{tag_type}] scored {total_tracks} tracks, wrote {len(col_sha)} prediction rows "
          f"(prob >= {min_store_prob}) -> {out_path}")
    return out_path


def _accumulate_parquet_batch(tagger, tags, batch, min_store_prob,
                              col_sha, col_artist, col_album, col_title, col_tag, col_prob) -> int:
    """Predict one batch and append rows above the probability floor to the column lists."""
    X = np.vstack([b[1] for b in batch])
    proba = tagger.predict_proba(X)
    for i, (sha, _emb, artist, album, title) in enumerate(batch):
        for j, tag in enumerate(tags):
            p = float(proba[i, j])
            if p >= min_store_prob:
                col_sha.append(sha)
                col_artist.append(artist)
                col_album.append(album)
                col_title.append(title)
                col_tag.append(tag)
                col_prob.append(p)
    return len(batch)


def _flush_batch(tagger, tags, batch, source, params, insert_fn) -> int:
    """Predict one batch, adaptively select each track's labels, and upsert them."""
    from music_embeddings.genre_selection import select_genres

    shas = [b[0] for b in batch]
    X = np.vstack([b[1] for b in batch])
    proba = tagger.predict_proba(X)
    rows: list[tuple[str, str, str, float]] = []
    for i, sha in enumerate(shas):
        pairs = zip(tags, proba[i])
        selected, _uncl = select_genres(
            pairs, min_conf=params.min_conf, frac=params.frac,
            floor=params.floor, cap=params.cap,
        )
        for label, p in selected:
            rows.append((sha, label, source, float(p)))
    insert_fn(rows)
    return len(rows)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("music_embeddings").setLevel(logging.INFO)
    report_label_coverage()
