"""
Playlist generation and Plex export module.

Generates discovery playlists with constraints:
- Promote unplayed / rarely played tracks (last_played > 6 months ago OR play_count < 3).
- Based on vector embedding similarity, mood, style, genre, or seed song.
- Diversity: 10+ distinct artists.
- Sequencing: No artist repeated within a sliding 4-song window.
- Sequencing: Ideally no album repeated within a sliding 10-song window.
- Directly exports the resulting playlist to Plex.
"""

import sys
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

from music_embeddings import config

logger = logging.getLogger("music_embeddings.playlist")

def print_available_labels(source: Optional[str] = None, filter_query: Optional[str] = None, limit: Optional[int] = None):
    """
    Prints a formatted table of available moods, styles, or genres to stdout.
    """
    from music_embeddings.datasource import LocalDataSource
    results = LocalDataSource().list_available_labels(source=source, filter_query=filter_query, limit=limit)
    if not results:
        title = source or "labels"
        q_str = f" matching '{filter_query}'" if filter_query else ""
        print(f"No available {title}{q_str} found in database.")
        return

    by_source = {}
    for r in results:
        by_source.setdefault(r['source'], []).append(r)

    source_names = {
        "allmusic mood": "AllMusic Moods",
        "allmusic style": "AllMusic Styles",
        "discogs genre": "Discogs Genres"
    }

    for src_key, items in by_source.items():
        disp_name = source_names.get(src_key, src_key.title())
        filter_str = f" (Filtered by '{filter_query}')" if filter_query else ""
        print(f"\n=== Available {disp_name}{filter_str} ({len(items)} total) ===")
        print(f"{'#':>3} | {'Label Name':<45} | {'Tracks':<8} | {'Avg Confidence':<15}")
        print("-" * 80)
        for idx, item in enumerate(items, 1):
            lbl = item['label'][:44]
            cnt = item['track_count']
            prob = f"{item['avg_prob'] * 100:.1f}%"
            print(f"{idx:3d} | {lbl:<45} | {cnt:<8} | {prob:<15}")
        print("-" * 80)

def generate_creative_assets(
    description: str,
    sample_tracks: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Uses DeepSeek v4-flash (routed through OpenRouter, high reasoning effort) to
    generate a clever playlist title and a matching AI-image-generation prompt for
    its cover art in a single call, so both stem from the same creative read of
    the tracklist. Samples artists, song titles, and album names across the
    playlist to build a rich prompt.

    v4-flash rather than v4-pro: pro's thinking mode was observed taking ~22s,
    close enough to the `creative` Function's 28s platform timeout that DO's
    gateway would sometimes kill the invocation and return its own generic
    error instead of ours. flash is DeepSeek's faster/cheaper reasoning tier
    (same reasoning-effort request shape) and comfortably clears it.

    Returns (title, image_prompt); either may be None on failure or missing API key.
    """
    import urllib.request
    import json

    key = api_key or config.OPENROUTER_API_KEY
    mod = model or config.OPENROUTER_TEXT_MODEL or "deepseek/deepseek-v4-flash"

    if not key:
        logger.debug("No OpenRouter API key provided. Skipping AI title/cover-prompt generation.")
        return None, None

    url = "https://openrouter.ai/api/v1/chat/completions"

    # Sample up to 12 representative tracks across beginning, middle, and end of playlist
    total = len(sample_tracks)
    if total <= 12:
        sampled = sample_tracks
    else:
        indices = np.linspace(0, total - 1, 12, dtype=int)
        sampled = [sample_tracks[i] for i in indices]

    track_lines = []
    for t in sampled:
        art = t.get('artist', 'Unknown Artist')
        tit = t.get('title', 'Untitled')
        alb = t.get('album', 'Unknown Album')
        track_lines.append(f'- "{tit}" by {art} (Album: {alb})')

    tracklist_formatted = "\n".join(track_lines)

    system_prompt = (
        "You are an elite radio DJ, master music curator, and art director renowned for creating iconic, "
        "witty, evocative, aesthetic playlist titles paired with vivid AI-image-generation prompts for their cover art. "
        "The title and image prompt must share one coherent creative vision - draw both from the same read of "
        "the artists, song titles, albums, and overall mood/theme, without sounding generic.\n\n"
        "Respond with EXACTLY two lines and nothing else (no commentary, no markdown, no code fences):\n"
        "TITLE: <a 2-5 word playlist title, no quotation marks, no trailing punctuation>\n"
        "IMAGE_PROMPT: <one vivid paragraph describing abstract or scenic imagery for a square playlist cover "
        "that captures the mix's mood - it must explicitly rule out any text, words, letters, numbers, titles, "
        "logos, signage, or poster-style layouts appearing in the image>"
    )

    user_prompt = (
        f"Playlist Seed/Theme: {description}\n\n"
        f"Featured Tracks (Song Title, Artist, and Album):\n"
        f"{tracklist_formatted}\n\n"
        f"Draw creative inspiration or subtle wordplay from the artist names, album titles, song names, or "
        f"overarching mood/theme. Aim for an indie radio show name, iconic mixtape title, or vivid artistic phrase."
    )

    payload = {
        "model": mod,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "reasoning": {"effort": "high"},
        "max_tokens": 4096
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            res = json.loads(response.read().decode("utf-8"))
            raw = res["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"OpenRouter call for playlist title/cover prompt failed: {e}")
        return None, None

    title = None
    image_prompt = None
    for line in raw.splitlines():
        line = line.strip()
        if not title and line.upper().startswith("TITLE:"):
            raw_title = line.split(":", 1)[1].strip()
            clean_title = raw_title.replace('"', '').replace("'", '').replace('*', '').strip('.! ')
            title = clean_title or None
        elif not image_prompt and line.upper().startswith("IMAGE_PROMPT:"):
            image_prompt = line.split(":", 1)[1].strip() or None

    if not title:
        logger.warning(f"Could not parse a title from DeepSeek response: {raw!r}")
    if not image_prompt:
        logger.warning(f"Could not parse an image prompt from DeepSeek response: {raw!r}")

    return title, image_prompt


def interpret_freeform_prompt(
    prompt: str,
    available_labels: List[str],
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> Optional[str]:
    """
    Maps a freeform vibe/description (e.g. "EDM Bangers", "rainy day") onto the single
    closest-matching mood/style/genre tag actually present in the library. The plain
    ILIKE substring match in resolve_label_centroid only catches inputs that already
    look like a real tag verbatim, so a colloquial phrase with no literal tag
    substring (most of them) would otherwise resolve to nothing.

    This is a simple classification call (pick one item from a fixed list), not
    creative writing, and runs inside `generate`'s own request/timeout budget as a
    fallback path rather than a separate Function - so unlike
    generate_creative_assets, thinking is explicitly disabled. deepseek-v4-pro
    reasons by default even without opting in, and left alone it burned 1-17+
    seconds per call (occasionally exhausting max_tokens on its chain-of-thought
    before ever producing an answer); disabling it brings every call down to ~1-2s
    with identical answer quality for this narrow a task.

    Returns one of `available_labels` verbatim (matched case-insensitively against
    the model's reply, to guard against paraphrasing/hallucination), or None if
    nothing reasonably fits or the call fails.
    """
    import urllib.request
    import json

    key = api_key or config.OPENROUTER_API_KEY
    mod = model or config.OPENROUTER_TEXT_MODEL or "deepseek/deepseek-v4-pro"

    if not key or not available_labels:
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"

    system_prompt = (
        "You match a freeform music vibe or description to the single closest mood, "
        "style, or genre tag from a fixed list. Respond with ONLY the exact tag text "
        "from the list, character-for-character, or the word NONE if nothing in the "
        "list reasonably fits the vibe. No punctuation, no quotes, no explanation."
    )
    user_prompt = f"Vibe: {prompt}\n\nAvailable tags:\n{', '.join(available_labels)}"

    payload = {
        "model": mod,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 32,
        "reasoning": {"enabled": False},
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode("utf-8"))
            raw = res["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"OpenRouter freeform-prompt interpretation failed: {e}")
        return None

    cleaned = raw.strip().strip('"').strip("'").rstrip(".")
    if cleaned.upper() == "NONE":
        return None

    label_lookup = {lbl.lower(): lbl for lbl in available_labels}
    return label_lookup.get(cleaned.lower())


def generate_ai_cover_image(
    description: str,
    sample_tracks: List[Dict[str, Any]],
    prompt: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> Optional[bytes]:
    """
    Generates a square playlist cover image via OpenRouter's Images API, themed on
    the playlist's seed description and a sample of its artists.
    If `prompt` is given (e.g. DeepSeek-crafted via generate_creative_assets), it is used
    directly; otherwise a generic template built from description + sampled artists is used.
    Returns raw PNG bytes, or None if no API key is configured or generation fails.
    """
    import urllib.request
    import json
    import base64

    key = api_key or config.OPENROUTER_API_KEY
    mod = model or config.OPENROUTER_IMAGE_MODEL or "black-forest-labs/flux.2-klein-4b"

    if not key:
        logger.debug("No OpenRouter API key provided. Skipping AI cover generation.")
        return None

    url = "https://openrouter.ai/api/v1/images"

    if prompt:
        final_prompt = prompt
    else:
        # Sample a handful of distinct artists across the playlist for prompt flavor
        total = len(sample_tracks)
        if total <= 8:
            sampled = sample_tracks
        else:
            indices = np.linspace(0, total - 1, 8, dtype=int)
            sampled = [sample_tracks[i] for i in indices]
        artists = sorted({t.get('artist', 'Unknown Artist') for t in sampled})

        final_prompt = (
            f"A vivid abstract or scenic digital illustration capturing a musical mood, "
            f"with no poster layout and no title treatment of any kind. "
            f"Theme/vibe: {description}. Inspired by the visual energy of artists such as: {', '.join(artists)}. "
            f"Focus purely on atmosphere, color, and imagery. "
            f"Strictly no text, no words, no letters, no numbers, no typography, no logos, no signage anywhere in the image. "
            f"Square composition, rich color palette, professional illustration."
        )

    payload = {
        "model": mod,
        "prompt": final_prompt,
        "aspect_ratio": "1:1",
        "output_format": "png"
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            res = json.loads(response.read().decode("utf-8"))
            b64_data = res["data"][0]["b64_json"]
            return base64.b64decode(b64_data)
    except Exception as e:
        logger.warning(f"OpenRouter API call for playlist cover image failed: {e}")
        return None

def _weighted_centroid(
    emb_rows: List[Tuple[str, Any]],
    sha_prob_map: Dict[str, float],
    matched_labels: List[str]
) -> Tuple[Optional[np.ndarray], List[str]]:
    """
    Shared math for resolve_label_centroid: probability-weighted, L2-normalized
    centroid over a set of (sha256, embedding) rows. Lives here (not datasource.py)
    so the query layer and the math stay separable and unit-testable.
    """
    if not emb_rows:
        return None, matched_labels

    vecs = []
    weights = []
    for sha, emb in emb_rows:
        vecs.append(np.asarray(emb, dtype=np.float32))
        weights.append(sha_prob_map[sha])

    vec_matrix = np.array(vecs)
    norms = np.linalg.norm(vec_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1e-10
    norm_vecs = vec_matrix / norms

    w_arr = np.array(weights, dtype=np.float32)
    centroid = np.average(norm_vecs, axis=0, weights=w_arr)
    centroid_norm = np.linalg.norm(centroid)
    if centroid_norm > 0:
        centroid /= centroid_norm

    return centroid, matched_labels

def _unweighted_centroid(rows: List[Tuple[str, Any]]) -> Tuple[Optional[np.ndarray], List[str]]:
    """
    Shared math for resolve_recent_activity_centroid: unweighted, L2-normalized
    centroid over a set of (sha256, embedding) rows. Lives here (not datasource.py)
    so the query layer and the math stay separable and unit-testable.
    """
    shas = [r[0] for r in rows]
    vec_matrix = np.array([np.asarray(r[1], dtype=np.float32) for r in rows])
    norms = np.linalg.norm(vec_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1e-10
    norm_vecs = vec_matrix / norms

    centroid = norm_vecs.mean(axis=0)
    centroid_norm = np.linalg.norm(centroid)
    if centroid_norm > 0:
        centroid /= centroid_norm

    return centroid, shas

def select_candidate_pool(sims: np.ndarray, pool_size: int, novelty: str = "similar") -> np.ndarray:
    """
    Selects a candidate pool of track indices from a similarity array, targeting a
    similarity band relative to the query vector:
    - "similar" (default): most similar tracks (existing/default behavior).
    - "step_away": a contiguous middle band of similarity - moderately different.
    - "different": least similar tracks - radically different.
    """
    order_desc = np.argsort(sims)[::-1]
    pool_size = max(1, min(pool_size, len(order_desc)))

    if novelty == "different":
        return order_desc[-pool_size:]
    if novelty == "step_away":
        start = max(0, (len(order_desc) - pool_size) // 2)
        return order_desc[start:start + pool_size]
    return order_desc[:pool_size]

def generate_playlist(
    prompt: Optional[str] = None,
    seed_song: Optional[str] = None,
    mood: Optional[str] = None,
    style: Optional[str] = None,
    genre: Optional[str] = None,
    count: int = 50,
    min_artists: int = 10,
    artist_window: int = 4,
    album_window: int = 10,
    ignore_play_history: bool = False,
    candidate_pool_size: int = 400,
    recent_days: Optional[int] = None,
    novelty: str = "similar",
    datasource=None,
    include_creative: bool = True
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Main playlist generation algorithm.
    Returns (playlist_tracks, metadata_dict).

    `datasource`, if given, is a datasource.DataSource (e.g. ParquetDataSource for the
    cloud/read-only app) that answers the playlist queries. When omitted (the default,
    used by the CLI), a LocalDataSource over the local DuckDB catalog is used.

    `include_creative`, when False, skips the DeepSeek title/cover-prompt call
    (generate_creative_assets - observed ~20s+ in thinking mode) and leaves
    meta['clever_title']/meta['cover_prompt'] as None. The cloud `generate` Function
    passes False here specifically so that cost is paid by its own separate `creative`
    Function call instead - the entire reason that split exists is to keep `generate`
    well under the Functions platform's 30s synchronous timeout; leaving this True by
    default here would silently defeat that for every caller of generate_playlist.
    """
    created_source = False
    if datasource is None:
        from music_embeddings.datasource import LocalDataSource
        datasource = LocalDataSource()
        created_source = True

    try:
        # Validate target length
        if count < 1:
            count = 50
        count = max(10, min(100, count))

        target_vectors = []
        descriptions = []
        seed_shas = set()

        # 1. Resolve seed song if provided
        if seed_song:
            seed_tracks = datasource.resolve_seed_songs(seed_song)
            if seed_tracks:
                st = seed_tracks[0] # pick top seed track match
                target_vectors.append(st['embedding'])
                seed_shas.add(st['sha256'])
                descriptions.append(f"Seed Song: '{st['artist']} - {st['title']}'")
            else:
                logger.warning(f"No matching seed song found for '{seed_song}'")

        # 2. Resolve specific mood/style/genre
        if mood:
            centroid, m_labels = datasource.resolve_label_centroid(mood, source="allmusic mood")
            if centroid is not None:
                target_vectors.append(centroid)
                descriptions.append(f"Mood: '{mood}' ({', '.join(m_labels[:3])})")
        if style:
            centroid, s_labels = datasource.resolve_label_centroid(style, source="allmusic style")
            if centroid is not None:
                target_vectors.append(centroid)
                descriptions.append(f"Style: '{style}' ({', '.join(s_labels[:3])})")
        if genre:
            centroid, g_labels = datasource.resolve_label_centroid(genre, source="discogs genre")
            if centroid is not None:
                target_vectors.append(centroid)
                descriptions.append(f"Genre: '{genre}' ({', '.join(g_labels[:3])})")

        # 3. Resolve freeform prompt if provided and no specific seed was matched yet
        if prompt and not target_vectors:
            # First check if prompt matches a song title or artist
            seed_tracks = datasource.resolve_seed_songs(prompt)
            if seed_tracks:
                st = seed_tracks[0]
                target_vectors.append(st['embedding'])
                seed_shas.add(st['sha256'])
                descriptions.append(f"Seed Track: '{st['artist']} - {st['title']}'")
            else:
                # Check labels across all sources for a literal substring match first
                centroid, p_labels = datasource.resolve_label_centroid(prompt)
                matched_tag = prompt
                if centroid is None:
                    # No literal match - most freeform vibes ("EDM Bangers", "rainy
                    # day") won't appear verbatim in the tag vocabulary even though
                    # they describe a real one, so ask DeepSeek to map the vibe onto
                    # an actual tag before giving up.
                    available_labels = [row['label'] for row in datasource.list_available_labels()]
                    interpreted = interpret_freeform_prompt(prompt, available_labels)
                    if interpreted:
                        centroid, p_labels = datasource.resolve_label_centroid(interpreted)
                        matched_tag = interpreted
                if centroid is not None:
                    target_vectors.append(centroid)
                    if matched_tag != prompt:
                        descriptions.append(f"Vibe: '{prompt}' -> '{matched_tag}' ({', '.join(p_labels[:3])})")
                    else:
                        descriptions.append(f"Tag Match: '{prompt}' ({', '.join(p_labels[:3])})")

        # 3b. Resolve recent listening activity, if requested
        recent_shas = set()
        recent_track_count = 0
        if recent_days:
            recent_centroid, recent_shas_list = datasource.resolve_recent_activity_centroid(days=recent_days)
            if recent_centroid is not None:
                target_vectors.append(recent_centroid)
                recent_shas = set(recent_shas_list)
                recent_track_count = len(recent_shas_list)
                novelty_label = {"similar": "similar to", "step_away": "a step away from", "different": "radically different from"}.get(novelty, novelty)
                descriptions.append(f"Recent listening (last {recent_days}d, {novelty_label} {recent_track_count} tracks)")
            else:
                logger.warning(f"Not enough recent listening history in the last {recent_days} days to build a centroid.")

        if not target_vectors:
            raise ValueError(
                f"Could not resolve any valid seed song, mood, style, genre, or recent activity from input. "
                f"Prompt='{prompt}', SeedSong='{seed_song}', Mood='{mood}', Style='{style}', Genre='{genre}', RecentDays='{recent_days}'"
            )

        # Combine target vectors into unified normalized query vector
        query_vec = np.average(target_vectors, axis=0)
        q_norm = np.linalg.norm(query_vec)
        if q_norm > 0:
            query_vec /= q_norm

        # 4. Fetch eligible tracks
        eligible_tracks = datasource.get_eligible_tracks(ignore_play_history=ignore_play_history)
        if not eligible_tracks:
            raise ValueError("No eligible tracks found in database matching play history criteria.")

        # Remove seed tracks and recently-played tracks from candidate pool
        exclude_shas = seed_shas | recent_shas
        eligible_tracks = [t for t in eligible_tracks if t['sha256'] not in exclude_shas]

        # 5. Compute vector similarities across eligible tracks
        emb_matrix = np.array([t['embedding'] for t in eligible_tracks], dtype=np.float32)
        norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1e-10
        emb_norm = emb_matrix / norms

        sims = np.dot(emb_norm, query_vec)

        # Attach similarity score to tracks
        for idx, t in enumerate(eligible_tracks):
            t['sim_score'] = float(sims[idx])

        # Select candidate pool by target similarity band (novelty)
        top_candidate_indices = select_candidate_pool(sims, candidate_pool_size, novelty=novelty)

        # 6. Sequence tracks satisfying artist & album sliding window constraints
        playlist = []
        used_indices = set()
        sha_to_matrix_idx = {t['sha256']: i for i, t in enumerate(eligible_tracks)}

        # Required distance for artist repeats: artist_window (e.g., 4 -> preceding 3 items must be different artist)
        artist_lookback = max(1, artist_window - 1)
        # Target distance for album repeats: album_window (e.g., 10 -> preceding 9 items must be different album)
        album_lookback_target = max(1, album_window - 1)

        for step in range(count):
            recent_artists = [t['artist'] for t in playlist[-artist_lookback:]] if len(playlist) >= 1 else []
            
            # Check unique artist safeguard
            current_artists = set(t['artist'] for t in playlist)
            artists_needed = min_artists - len(current_artists)
            slots_left = count - step
            force_new_artist = (artists_needed > 0 and slots_left <= artists_needed)

            best_candidate_idx = None
            best_candidate_score = -9999.0

            # Try album lookback windows from target down to 0 (graceful degradation for album spacing if necessary)
            for alb_lb in range(album_lookback_target, -1, -1):
                recent_albums = [t['album'] for t in playlist[-alb_lb:]] if alb_lb > 0 else []

                candidates = []
                for idx in top_candidate_indices:
                    if idx in used_indices:
                        continue
                    cand_artist = eligible_tracks[idx]['artist']
                    cand_album = eligible_tracks[idx]['album']

                    # Strict artist window requirement
                    if cand_artist in recent_artists:
                        continue
                    # Unique artist safeguard requirement
                    if force_new_artist and cand_artist in current_artists:
                        continue
                    # Album window requirement (graded)
                    if cand_album in recent_albums:
                        continue

                    candidates.append(idx)

                if candidates:
                    for idx in candidates:
                        cand_sim = eligible_tracks[idx]['sim_score']
                        # Acoustic flow score relative to preceding track
                        if len(playlist) > 0:
                            prev_matrix_idx = sha_to_matrix_idx[playlist[-1]['sha256']]
                            flow_sim = float(np.dot(emb_norm[idx], emb_norm[prev_matrix_idx]))
                        else:
                            flow_sim = cand_sim

                        # Artist frequency penalty to encourage high diversity
                        artist_freq = sum(1 for t in playlist if t['artist'] == eligible_tracks[idx]['artist'])

                        # Composite score
                        score = 0.60 * cand_sim + 0.40 * flow_sim - 0.08 * artist_freq
                        if score > best_candidate_score:
                            best_candidate_score = score
                            best_candidate_idx = idx
                    break

            if best_candidate_idx is not None:
                used_indices.add(best_candidate_idx)
                playlist.append(eligible_tracks[best_candidate_idx])
            else:
                logger.warning(f"Could not find candidate satisfying all constraints at step {step + 1}/{count}")
                break

        unique_artists = len(set(t['artist'] for t in playlist))
        unique_albums = len(set(t['album'] for t in playlist))

        desc_str = " | ".join(descriptions)
        clever_title, cover_prompt = generate_creative_assets(desc_str, playlist) if include_creative else (None, None)

        meta = {
            'description': desc_str,
            'clever_title': clever_title,
            'cover_prompt': cover_prompt,
            'target_count': count,
            'generated_count': len(playlist),
            'unique_artists': unique_artists,
            'unique_albums': unique_albums,
            'ignore_play_history': ignore_play_history,
            'recent_days': recent_days,
            'novelty': novelty,
            'recent_track_count': recent_track_count
        }

        return playlist, meta

    finally:
        if created_source:
            datasource.con.close()

def push_playlist_to_plex(
    playlist_tracks: List[Dict[str, Any]],
    title: str,
    overwrite: bool = True,
    plex_url: Optional[str] = None,
    plex_token: Optional[str] = None,
    cover_image_bytes: Optional[bytes] = None,
    cover_url: Optional[str] = None
) -> str:
    """
    Pushes the generated track list to Plex Server as a Playlist.
    Returns the web URL or summary string of the created Plex playlist.
    """
    from plexapi.server import PlexServer

    url = plex_url or config.PLEX_URL
    token = plex_token or config.PLEX_TOKEN

    if not url or not token:
        raise ValueError("Plex Server URL or Token not configured in environment or args.")

    logger.info(f"Connecting to Plex Server at '{url}'...")
    plex = PlexServer(url, token)

    rating_keys = [t['rating_key'] for t in playlist_tracks if 'rating_key' in t]
    if not rating_keys:
        raise ValueError("No valid Plex rating keys found in playlist tracks.")

    print(f"Fetching {len(rating_keys)} track items from Plex...")
    plex_items = []
    for rk in rating_keys:
        try:
            item = plex.fetchItem(rk)
            plex_items.append(item)
        except Exception as e:
            logger.warning(f"Could not fetch Plex item for ratingKey {rk}: {e}")

    if not plex_items:
        raise ValueError("Failed to retrieve track objects from Plex Server.")

    # Check existing playlists
    existing_playlist = None
    try:
        playlists = plex.playlists()
        for pl in playlists:
            if pl.title.lower() == title.lower():
                existing_playlist = pl
                break
    except Exception as e:
        logger.warning(f"Error checking existing playlists: {e}")

    if existing_playlist:
        if overwrite:
            print(f"Overwriting existing Plex playlist '{existing_playlist.title}'...")
            existing_playlist.delete()
            created_pl = plex.createPlaylist(title, items=plex_items)
        else:
            print(f"Playlist '{title}' already exists. Updating items...")
            existing_playlist.removeItems(existing_playlist.items())
            existing_playlist.addItems(plex_items)
            created_pl = existing_playlist
    else:
        print(f"Creating new Plex playlist '{title}' with {len(plex_items)} tracks...")
        created_pl = plex.createPlaylist(title, items=plex_items)

    if cover_image_bytes or cover_url:
        try:
            if cover_image_bytes:
                created_pl.uploadPoster(filepath=cover_image_bytes)
            elif cover_url.startswith("http://") or cover_url.startswith("https://"):
                created_pl.uploadPoster(url=cover_url)
            else:
                created_pl.uploadPoster(filepath=cover_url)  # local file path
        except Exception as e:
            logger.warning(f"Failed to upload cover image for Plex playlist '{created_pl.title}': {e}")

    return f"Successfully created Plex playlist '{created_pl.title}' with {len(plex_items)} tracks."


def delete_playlist_from_plex(
    title: str,
    plex_url: Optional[str] = None,
    plex_token: Optional[str] = None
) -> bool:
    """
    Deletes a Plex playlist by title (case-insensitive) if it exists.
    Returns True if a playlist was found and deleted, False if none matched.
    """
    from plexapi.server import PlexServer

    url = plex_url or config.PLEX_URL
    token = plex_token or config.PLEX_TOKEN
    if not url or not token:
        raise ValueError("Plex Server URL or Token not configured in environment or args.")

    plex = PlexServer(url, token)
    for pl in plex.playlists():
        if pl.title.lower() == title.lower():
            pl.delete()
            return True
    return False
