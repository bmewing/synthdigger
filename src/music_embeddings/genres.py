import logging
import sys
import os
from pathlib import Path
from music_embeddings import config
from music_embeddings.embedder import MusicEmbedder
from music_embeddings.database import get_connection, insert_track_labels_batch
from music_embeddings.genre_selection import selected_prob_rows
from music_embeddings.labels import SOURCE_DISCOGS_GENRE

logger = logging.getLogger("music_embeddings.genres")


def process_genre_predictions(limit: int = None, force: bool = False, trim: bool = True) -> None:
    """
    Scans existing track embeddings in the database, runs Discogs genre prediction
    inference for unpredicted tracks, and writes the genre labels to
    embedding.track_labels (source 'discogs genre').

    When ``trim`` is True (default) each track's 400 raw probabilities are reduced
    to the adaptively-selected genres before insertion (see genre_selection); pass
    trim=False to store all 400.
    """
    model_path = Path(config.MODEL_PATH)
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model file not found at '{model_path}'. Please run download-model first."
        )
        
    print("Connecting to database to check existing track embeddings...")
    conn = get_connection()
    
    tracks_to_process = []
    try:
        with conn.cursor() as cur:
            if force:
                cur.execute("SELECT sha256, source_path FROM embedding.track_embeddings;")
            else:
                cur.execute("""
                    SELECT e.sha256, e.source_path
                    FROM embedding.track_embeddings e
                    LEFT JOIN (
                        SELECT DISTINCT sha256 FROM embedding.track_labels
                        WHERE source = 'discogs genre'
                    ) p ON e.sha256 = p.sha256
                    WHERE p.sha256 IS NULL;
                """)
            tracks_to_process = cur.fetchall()
    except Exception as e:
        print(f"Database query failed: {e}")
        return
    finally:
        conn.close()
        
    total_found = len(tracks_to_process)
    print(f"Found {total_found} tracks requiring genre predictions.")
    
    if limit:
        tracks_to_process = tracks_to_process[:limit]
        print(f"Applying limit: Processing first {len(tracks_to_process)} tracks.")
        
    if not tracks_to_process:
        print("All tracks already have genre predictions populated. Exiting.")
        return
        
    # Initialize embedder
    embedder = MusicEmbedder(model_path)

    # Base search root for resolving relative source_paths (optional)
    network_base = Path(config.MUSIC_LIBRARY_ROOT) if config.MUSIC_LIBRARY_ROOT else None

    success_count = 0
    skipped_count = 0
    error_count = 0

    for idx, (sha256, source_path) in enumerate(tracks_to_process, 1):
        # Resolve full path
        audio_path = Path(source_path)
        if not audio_path.exists():
            # Try resolving relative to the music library root, if configured
            alt_path = network_base / source_path.replace("\\", "/") if network_base else None
            if alt_path is not None and alt_path.exists():
                audio_path = alt_path
            else:
                hint = "" if network_base else " (set MUSIC_LIBRARY_ROOT if your library lives on a share/mount)"
                print(f"[{idx}/{len(tracks_to_process)}] Error: Audio file not found at '{source_path}'{hint}")
                error_count += 1
                continue
                
        print(f"[{idx}/{len(tracks_to_process)}] Predicting genres: {audio_path.name}")
        try:
            _, meta, genre_probs = embedder.embed_and_predict_file(audio_path)

            # Adaptively trim to the meaningful genres (or keep all 400 if trim=False)
            if trim:
                selected = selected_prob_rows(sha256, genre_probs)  # (sha, genre, prob)
            else:
                selected = [(sha256, genre_style, prob) for genre_style, prob in genre_probs.items()]

            # Write to the unified track_labels table with explicit provenance.
            rows = [(sha, label, SOURCE_DISCOGS_GENRE, prob) for sha, label, prob in selected]
            insert_track_labels_batch(rows)
            print(f"  -> Success: {len(rows)} genre labels inserted into database.")
            success_count += 1
        except Exception as e:
            print(f"  -> Error predicting genres for '{audio_path.name}': {e}", file=sys.stderr)
            error_count += 1
            
    print(f"\nGenre Prediction Finished: {success_count} succeeded, {skipped_count} skipped, {error_count} failed.")
    print(f"Total prediction rows added to database: {success_count * 400}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logging.getLogger("music_embeddings").setLevel(logging.INFO)
    process_genre_predictions()
