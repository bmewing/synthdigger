from plexapi.server import PlexServer
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from music_embeddings import config
from music_embeddings.embedder import MusicEmbedder
from music_embeddings.serialization import save_embedding_and_metadata, calculate_sha256
from music_embeddings.database import get_connection, insert_embedding, insert_track_labels_batch, SQL_UTC_NOW
from music_embeddings.genre_selection import selected_prob_rows
from music_embeddings.labels import SOURCE_DISCOGS_GENRE

logger = logging.getLogger(__name__)


def _relative_library_path(path_str: str) -> str:
    """
    Case-preserving, forward-slashed slice of `path_str` starting at the first
    configured PLEX_MUSIC_FOLDERS anchor folder. Falls back to the whole
    (slashed) path when no anchor matches or none are configured.

    Plex reports paths as its host sees them ("D:\\Media\\Plex Music\\...") while
    scan-time paths were recorded through whatever mount this machine used -
    slicing both at a shared anchor folder makes them comparable.
    """
    slashed = path_str.replace("\\", "/")
    lower = slashed.lower()
    for folder in config.PLEX_MUSIC_FOLDERS:
        idx = lower.find(folder.lower())
        if idx >= 0:
            return slashed[idx:]
    return slashed


def _match_key(path_str: str) -> str:
    """Case-insensitive matching key for a library path (see _relative_library_path)."""
    return _relative_library_path(path_str).lower().replace("\uf025", "?")


def sync_plex_full_taxonomy() -> None:
    """
    Connects to Plex Server and pulls all Artist, Album, and Track metadata separately,
    including AllMusic genres, styles, moods, summaries, play counts, and ratings,
    and populates the 3 metadata tables in the local DuckDB catalog.
    """
    print("Connecting to database...")
    db_conn = get_connection()
    
    # 1. Index local embeddings by library-relative path for track matching
    db_suffix_to_sha = {}
    try:
        with db_conn.cursor() as cur:
            cur.execute("SELECT sha256, source_path FROM embedding.track_embeddings;")
            for sha256, source_path in cur.fetchall():
                db_suffix_to_sha[_match_key(source_path)] = sha256
    except Exception as e:
        logger.error(f"Failed to query local database tracks: {e}")
        db_conn.close()
        return
        
    print(f"Loaded and indexed {len(db_suffix_to_sha)} track embeddings from local database.")
    
    # 2. Connect to Plex Server
    if not config.PLEX_URL or not config.PLEX_TOKEN:
        print("Error: PLEX_URL or PLEX_TOKEN not configured in .env file.")
        db_conn.close()
        return
        
    print(f"Connecting to Plex Server at {config.PLEX_URL}...")
    try:
        plex = PlexServer(config.PLEX_URL, config.PLEX_TOKEN)
        print("Successfully connected to Plex Server!")
    except Exception as e:
        print(f"Failed to connect to Plex Server: {e}")
        db_conn.close()
        return
        
    all_sections = plex.library.sections()
    music_libraries = [
        s for s in all_sections 
        if s.type == "artist" and any(k in s.title.lower() for k in ["music", "classical", "scores"])
    ]
    if not music_libraries:
        music_libraries = [s for s in all_sections if s.type == "artist"]
        
    if not music_libraries:
        print("No Music/Artist sections found on Plex Server. Exiting.")
        db_conn.close()
        return
        
    try:
        with db_conn.cursor() as cur:
            for music_section in music_libraries:
                print(f"\n==================================================")
                print(f"Processing Plex Library: '{music_section.title}'")
                
                # --- STEP A: Sync Artists ---
                print(f"Fetching artists from '{music_section.title}'...")
                artists = music_section.search(libtype='artist')
                print(f"Found {len(artists)} artists. Populating artist metadata table...")
                
                artist_upsert_query = f"""
                INSERT INTO embedding.plex_artist_metadata (
                    rating_key, artist_name, summary, genres, styles, moods, added_at, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, {SQL_UTC_NOW})
                ON CONFLICT (rating_key) DO UPDATE SET
                    artist_name = EXCLUDED.artist_name,
                    summary = EXCLUDED.summary,
                    genres = EXCLUDED.genres,
                    styles = EXCLUDED.styles,
                    moods = EXCLUDED.moods,
                    added_at = EXCLUDED.added_at,
                    last_synced_at = {SQL_UTC_NOW};
                """
                
                artist_rows = []
                for a in artists:
                    g_tags = [g.tag for g in a.genres] if hasattr(a, 'genres') and a.genres else []
                    s_tags = [s.tag for s in a.styles] if hasattr(a, 'styles') and a.styles else []
                    m_tags = [m.tag for m in a.moods] if hasattr(a, 'moods') and a.moods else []
                    summary_text = getattr(a, 'summary', None)
                    added_at = getattr(a, 'addedAt', None)
                    artist_rows.append((a.ratingKey, a.title, summary_text, g_tags, s_tags, m_tags, added_at))
                    
                if artist_rows:
                    cur.executemany(artist_upsert_query, artist_rows)
                print(f"Successfully synchronized {len(artist_rows)} artists.")
                
                # --- STEP B: Sync Albums ---
                print(f"\nFetching albums from '{music_section.title}'...")
                albums = music_section.search(libtype='album')
                print(f"Found {len(albums)} albums. Populating album metadata table...")
                
                album_upsert_query = f"""
                INSERT INTO embedding.plex_album_metadata (
                    rating_key, artist_rating_key, album_name, artist_name, year, summary,
                    genres, styles, moods, added_at, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {SQL_UTC_NOW})
                ON CONFLICT (rating_key) DO UPDATE SET
                    artist_rating_key = EXCLUDED.artist_rating_key,
                    album_name = EXCLUDED.album_name,
                    artist_name = EXCLUDED.artist_name,
                    year = EXCLUDED.year,
                    summary = EXCLUDED.summary,
                    genres = EXCLUDED.genres,
                    styles = EXCLUDED.styles,
                    moods = EXCLUDED.moods,
                    added_at = EXCLUDED.added_at,
                    last_synced_at = {SQL_UTC_NOW};
                """
                
                album_rows = []
                for alb in albums:
                    g_tags = [g.tag for g in alb.genres] if hasattr(alb, 'genres') and alb.genres else []
                    s_tags = [s.tag for s in alb.styles] if hasattr(alb, 'styles') and alb.styles else []
                    m_tags = [m.tag for m in alb.moods] if hasattr(alb, 'moods') and alb.moods else []
                    summary_text = getattr(alb, 'summary', None)
                    year_val = getattr(alb, 'year', None)
                    added_at = getattr(alb, 'addedAt', None)
                    parent_key = getattr(alb, 'parentRatingKey', None)
                    artist_name = getattr(alb, 'grandparentTitle', None) or getattr(alb, 'artistTitle', None)
                    album_rows.append((
                        alb.ratingKey, parent_key, alb.title, artist_name, year_val,
                        summary_text, g_tags, s_tags, m_tags, added_at
                    ))
                    
                if album_rows:
                    cur.executemany(album_upsert_query, album_rows)
                print(f"Successfully synchronized {len(album_rows)} albums.")
                
                # --- STEP C: Sync Tracks ---
                print(f"\nFetching tracks from '{music_section.title}'...")
                tracks = music_section.searchTracks()
                print(f"Found {len(tracks)} tracks. Populating track metadata table...")
                
                track_upsert_query = f"""
                INSERT INTO embedding.plex_track_metadata (
                    plex_rating_key, album_rating_key, sha256, play_count, last_played_at,
                    user_rating, artist_name, album_name, track_title, genres, moods, added_to_plex_at, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {SQL_UTC_NOW})
                ON CONFLICT (plex_rating_key) DO UPDATE SET
                    album_rating_key = EXCLUDED.album_rating_key,
                    sha256 = EXCLUDED.sha256,
                    play_count = EXCLUDED.play_count,
                    last_played_at = EXCLUDED.last_played_at,
                    user_rating = EXCLUDED.user_rating,
                    artist_name = EXCLUDED.artist_name,
                    album_name = EXCLUDED.album_name,
                    track_title = EXCLUDED.track_title,
                    genres = EXCLUDED.genres,
                    moods = EXCLUDED.moods,
                    added_to_plex_at = EXCLUDED.added_to_plex_at,
                    last_synced_at = {SQL_UTC_NOW};
                """
                
                matched_tracks = 0
                for track in tracks:
                    g_tags = [g.tag for g in track.genres] if hasattr(track, 'genres') and track.genres else []
                    m_tags = [m.tag for m in track.moods] if hasattr(track, 'moods') and track.moods else []
                    album_key = getattr(track, 'parentRatingKey', None)
                    
                    for media in track.media:
                        for part in media.parts:
                            matched_sha = db_suffix_to_sha.get(_match_key(part.file))
                            if matched_sha:
                                play_count = track.viewCount or 0
                                last_played = track.lastViewedAt
                                user_rating = track.userRating
                                artist_name = track.grandparentTitle
                                album_name = track.parentTitle
                                track_title = track.title
                                added_at = track.addedAt
                                
                                cur.execute(track_upsert_query, (
                                    track.ratingKey, album_key, matched_sha, play_count, last_played,
                                    user_rating, artist_name, album_name, track_title, g_tags, m_tags, added_at
                                ))
                                matched_tracks += 1

                print(f"Successfully synchronized {matched_tracks} matched tracks.")

    except Exception as e:
        print(f"Error during full taxonomy sync: {e}")
    finally:
        db_conn.close()
        
    print(f"\nFull Metadata & Taxonomy Sync Finished!")

def sync_plex_metadata() -> None:
    """Legacy alias for backward compatibility."""
    sync_plex_full_taxonomy()

def sync_incremental_plex() -> None:
    """
    Finds the most recent added_to_plex_at timestamp in the local catalog, queries
    Plex Server for tracks added after that timestamp, resolves their file paths,
    generates embeddings and Discogs 400-genre predictions, and updates all 3
    database tables.
    """
    model_path = Path(config.MODEL_PATH)
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found at '{model_path}'. Run download-model first.")

    print("Querying database for most recent added_to_plex_at timestamp...")
    db_conn = get_connection()
    
    max_added_utc = None
    try:
        with db_conn.cursor() as cur:
            cur.execute("SELECT MAX(added_to_plex_at) FROM embedding.plex_track_metadata;")
            max_added = cur.fetchone()[0]
            if max_added:
                if max_added.tzinfo:
                    max_added_utc = max_added.astimezone(timezone.utc)
                else:
                    max_added_utc = max_added.replace(tzinfo=timezone.utc)
    except Exception as e:
        print(f"Database timestamp query failed: {e}")
        db_conn.close()
        return
        
    if max_added_utc:
        print(f"Baseline added timestamp in DB: {max_added_utc}")
    else:
        max_added_utc = datetime.min.replace(tzinfo=timezone.utc)
        print("No existing tracks in metadata table. Defaulting to epoch 0.")

    # Connect to Plex Server
    if not config.PLEX_URL or not config.PLEX_TOKEN:
        print("Error: PLEX_URL or PLEX_TOKEN not configured in .env file.")
        db_conn.close()
        return
        
    print(f"Connecting to Plex Server at {config.PLEX_URL}...")
    try:
        plex = PlexServer(config.PLEX_URL, config.PLEX_TOKEN)
        print("Successfully connected to Plex Server!")
    except Exception as e:
        print(f"Failed to connect to Plex Server: {e}")
        db_conn.close()
        return

    all_sections = plex.library.sections()
    music_libraries = [
        s for s in all_sections 
        if s.type == "artist" and any(k in s.title.lower() for k in ["music", "classical", "scores"])
    ]
    if not music_libraries:
        music_libraries = [s for s in all_sections if s.type == "artist"]

    print(f"Checking {len(music_libraries)} Plex music libraries for tracks added after baseline timestamp...")
    new_plex_tracks = []
    
    for music_section in music_libraries:
        try:
            section_tracks = music_section.searchTracks()
            for track in section_tracks:
                if track.addedAt:
                    track_added_utc = (
                        track.addedAt.astimezone(timezone.utc) 
                        if track.addedAt.tzinfo 
                        else track.addedAt.replace(tzinfo=timezone.utc)
                    )
                    if track_added_utc > max_added_utc:
                        new_plex_tracks.append(track)
        except Exception as e:
            print(f"Error searching section '{music_section.title}': {e}")
            
    print(f"\nFound {len(new_plex_tracks)} newly added tracks in Plex!")
    if not new_plex_tracks:
        print("Database is already up to date. No new tracks to process.")
        db_conn.close()
        return

    # Initialize embedder
    embedder = MusicEmbedder(model_path)
    output_dir = Path(config.OUTPUT_DIR)
    network_base = Path(config.MUSIC_LIBRARY_ROOT) if config.MUSIC_LIBRARY_ROOT else None

    success_count = 0
    error_count = 0

    for idx, track in enumerate(new_plex_tracks, 1):
        print(f"\n[{idx}/{len(new_plex_tracks)}] Processing new Plex track: '{track.title}' by '{track.grandparentTitle}'")

        for media in track.media:
            for part in media.parts:
                relative_path = _relative_library_path(part.file)

                if network_base is not None:
                    local_path = network_base / relative_path
                else:
                    # No MUSIC_LIBRARY_ROOT configured: try Plex's own reported
                    # path, which is correct when this pipeline runs on the
                    # Plex host itself.
                    local_path = Path(part.file)

                if not local_path.exists():
                    alt_str = str(local_path).replace("?", "\uf025")
                    if Path(alt_str).exists():
                        local_path = Path(alt_str)
                    else:
                        hint = "" if network_base is not None else (
                            " (set MUSIC_LIBRARY_ROOT to the path where this machine "
                            "can reach your Plex media, e.g. an SMB share or mount)"
                        )
                        print(f"  -> Error: audio file not found on disk at '{local_path}'{hint}", file=sys.stderr)
                        error_count += 1
                        continue
                        
                try:
                    sha256 = calculate_sha256(local_path)
                    embedding, meta, genre_probs = embedder.embed_and_predict_file(local_path)
                    
                    save_embedding_and_metadata(
                        output_dir=output_dir,
                        audio_path=local_path,
                        embedding=embedding,
                        metadata_info=meta,
                        model_path=model_path,
                        source_path=relative_path
                    )
                    
                    stat = local_path.stat()
                    insert_embedding(
                        sha256=sha256,
                        source_path=relative_path,
                        source_filename=local_path.name,
                        file_size=stat.st_size,
                        file_mtime=stat.st_mtime,
                        audio_duration=meta["duration"],
                        embedding_model_name="EffnetDiscogs",
                        model_filename=model_path.name,
                        embedding=embedding
                    )
                    
                    # Adaptively trim genres and write to unified track_labels
                    selected = selected_prob_rows(sha256, genre_probs)
                    genre_rows = [(s, label, SOURCE_DISCOGS_GENRE, prob) for s, label, prob in selected]
                    insert_track_labels_batch(genre_rows)
                    
                    with db_conn.cursor() as cur:
                        play_count = track.viewCount or 0
                        last_played = track.lastViewedAt
                        user_rating = track.userRating
                        artist_name = track.grandparentTitle
                        album_name = track.parentTitle
                        track_title = track.title
                        added_at = track.addedAt
                        album_key = getattr(track, 'parentRatingKey', None)
                        g_tags = [g.tag for g in track.genres] if hasattr(track, 'genres') and track.genres else []
                        m_tags = [m.tag for m in track.moods] if hasattr(track, 'moods') and track.moods else []
                        
                        insert_query = f"""
                        INSERT INTO embedding.plex_track_metadata (
                            plex_rating_key, album_rating_key, sha256, play_count, last_played_at,
                            user_rating, artist_name, album_name, track_title, genres, moods, added_to_plex_at, last_synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {SQL_UTC_NOW})
                        ON CONFLICT (plex_rating_key) DO UPDATE SET
                            album_rating_key = EXCLUDED.album_rating_key,
                            sha256 = EXCLUDED.sha256,
                            play_count = EXCLUDED.play_count,
                            last_played_at = EXCLUDED.last_played_at,
                            user_rating = EXCLUDED.user_rating,
                            artist_name = EXCLUDED.artist_name,
                            album_name = EXCLUDED.album_name,
                            track_title = EXCLUDED.track_title,
                            genres = EXCLUDED.genres,
                            moods = EXCLUDED.moods,
                            added_to_plex_at = EXCLUDED.added_to_plex_at,
                            last_synced_at = {SQL_UTC_NOW};
                        """
                        cur.execute(insert_query, (
                            track.ratingKey, album_key, sha256, play_count, last_played,
                            user_rating, artist_name, album_name, track_title, g_tags, m_tags, added_at
                        ))

                    print(f"  -> Success! Fully embedded, predicted, and stored in database.")
                    success_count += 1
                    
                except Exception as e:
                    print(f"  -> Error processing '{track.title}': {e}", file=sys.stderr)
                    error_count += 1

    db_conn.close()
    print(f"\nIncremental Sync Finished: {success_count} succeeded, {error_count} failed.")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logging.getLogger("music_embeddings").setLevel(logging.INFO)
    sync_plex_full_taxonomy()
