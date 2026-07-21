"""
Adaptive per-track genre selection for the 400-class Discogs predictions.

The Discogs-EffNet head emits an independent probability for each of 400
genre/styles. Sorted descending, a track's probabilities form a convex decay
(a few meaningful genres, then a long diffuse tail toward zero) -- NOT a sigmoid,
so there is no clean plateau to threshold on. A fixed top-k over-labels simple
tracks and under-labels genuinely eclectic ones.

This module selects a variable number of genres per track using a rule validated
on the real distribution:

  * Confidence gate: if the top probability is below ``min_conf`` the model has no
    confident genre (near-silence, codas, spoken word, noise) -> the track is
    *unclassifiable* and gets zero genres. This is the crucial guard: a flat
    probability curve usually means "model is unsure", not "complex song", so
    naive adaptive methods otherwise pile dozens of spurious genres onto
    non-music tracks.
  * Adaptive threshold: keep genres with ``prob >= max(floor, frac * top1)``. The
    relative term auto-tightens for peaked tracks; the absolute floor kills the
    diffuse tail.
  * Cap: never keep more than ``cap`` genres.

Defaults (min_conf=0.10, frac=0.25, floor=0.05, cap=10) give, on a 5k sample:
~4.5% unclassifiable, median 7 genres among labeled tracks, 1 for clean solo
recordings, up to the cap for dense eclectic tracks.
"""

from dataclasses import dataclass

# Tunable defaults (see module docstring for how these were chosen).
DEFAULT_MIN_CONF = 0.10
DEFAULT_FRAC = 0.25
DEFAULT_FLOOR = 0.05
DEFAULT_CAP = 10


@dataclass
class SelectionParams:
    min_conf: float = DEFAULT_MIN_CONF
    frac: float = DEFAULT_FRAC
    floor: float = DEFAULT_FLOOR
    cap: int = DEFAULT_CAP


def select_genres(
    pairs,
    min_conf: float = DEFAULT_MIN_CONF,
    frac: float = DEFAULT_FRAC,
    floor: float = DEFAULT_FLOOR,
    cap: int = DEFAULT_CAP,
):
    """
    Select the meaningful genres for one track.

    Args:
        pairs: iterable of (genre_style, probability). Order does not matter;
               it is sorted internally.
        min_conf, frac, floor, cap: selection knobs (see module docstring).

    Returns:
        (selected, unclassifiable) where
          selected: list of (genre_style, probability) kept, sorted by
                    probability descending (empty iff unclassifiable).
          unclassifiable: True when the top probability is below ``min_conf``.
    """
    items = sorted(((g, float(p)) for g, p in pairs), key=lambda gp: gp[1], reverse=True)
    if not items:
        return [], True

    top1 = items[0][1]
    if top1 < min_conf:
        return [], True

    threshold = max(floor, frac * top1)
    selected = [(g, p) for g, p in items if p >= threshold]
    # The top genre always survives (top1 >= min_conf >= ... may be < threshold only
    # if floor > top1, which the confidence gate already precludes for floor <= min_conf).
    if not selected:
        selected = [items[0]]
    return selected[:cap], False


def selected_prob_rows(sha256: str, genre_probs, params: "SelectionParams | None" = None):
    """
    Convenience for the write path: apply ``select_genres`` to a track's genre
    probability mapping and return DB-ready (sha256, genre_style, probability)
    rows for only the selected genres. Returns [] for unclassifiable tracks.

    ``genre_probs`` may be a dict {genre: prob} or an iterable of (genre, prob).
    """
    params = params or SelectionParams()
    pairs = genre_probs.items() if hasattr(genre_probs, "items") else genre_probs
    selected, _uncl = select_genres(
        pairs, min_conf=params.min_conf, frac=params.frac,
        floor=params.floor, cap=params.cap,
    )
    return [(sha256, g, p) for g, p in selected]
