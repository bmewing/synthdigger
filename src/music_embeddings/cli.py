import argparse
import sys
from pathlib import Path
import numpy as np
import logging

# Reconfigure stdout/stderr to handle Unicode characters correctly on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')

from music_embeddings.embedder import MusicEmbedder
from music_embeddings.serialization import save_embedding_and_metadata, calculate_sha256
from music_embeddings.models import download_default_model
from music_embeddings import config
from music_embeddings.version import APP_VERSION, SCHEMA_VERSION

# Set up logging to stdout (root logger defaults to WARNING to suppress third-party library spam)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
# Enable INFO logging specifically for our package modules
logging.getLogger("music_embeddings").setLevel(logging.INFO)
logger = logging.getLogger("music_embeddings.cli")

def _print_schema_warning_if_needed():
    """Non-fatal heads-up printed before DB-touching commands run, so a user on a
    stale catalog learns they need upgrade steps instead of hitting a confusing
    failure later. Silent when the catalog is current or not yet created."""
    try:
        from music_embeddings.database import check_schema_status
        status, current, expected = check_schema_status()
    except Exception:
        return  # never let the check itself break a command
    if status == "needs_upgrade":
        print(
            f"WARNING: your catalog is schema v{current} but this SynthDigger build expects "
            f"v{expected}. Run the upgrade steps in CHANGELOG.md - some commands may "
            f"fail until you do. (`synthdigger version` for details.)",
            file=sys.stderr,
        )
    elif status == "code_outdated":
        print(
            f"WARNING: your catalog is schema v{current}, newer than this SynthDigger build "
            f"(expects v{expected}). Update SynthDigger to match. (`synthdigger version` for details.)",
            file=sys.stderr,
        )


def main():
    parser = argparse.ArgumentParser(
        prog="synthdigger",
        description="SynthDigger - know your Plex library by its sound. Builds a semantic "
                    "audio index of your music (Discogs-EffNet embeddings) and generates "
                    "discovery playlists.",
    )
    parser.add_argument("--version", action="version", version=f"SynthDigger {APP_VERSION}")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # version command (richer than --version: also reports catalog schema status)
    subparsers.add_parser("version", help="Show the SynthDigger version and whether the local catalog needs upgrade steps")

    # init-db command (create the empty catalog; same as `python -m music_embeddings.database`)
    subparsers.add_parser("init-db", help="Create the local DuckDB catalog file if it doesn't exist yet")

    # embed command
    embed_parser = subparsers.add_parser("embed", help="Extract embedding for a local audio file")
    embed_parser.add_argument("audio_path", type=str, help="Path to local audio file")
    embed_parser.add_argument("--model-path", type=str, default=None, help="Path to model .onnx file")
    embed_parser.add_argument("--output-dir", type=str, default=None, help="Directory to save generated files")
    embed_parser.add_argument("--force", action="store_true", help="Overwrite existing output files and database records")
    embed_parser.add_argument("--max-seconds", type=float, default=None, help="Maximum audio duration to analyze")
    
    # scan command
    scan_parser = subparsers.add_parser(
        "scan", 
        help="Recursively scan a directory for audio files and extract embeddings"
    )
    scan_parser.add_argument("scan_dir", type=str, help="Directory to scan")
    scan_parser.add_argument("--model-path", type=str, default=None, help="Path to model .onnx file")
    scan_parser.add_argument("--output-dir", type=str, default=None, help="Directory to save generated files")
    scan_parser.add_argument("--force", action="store_true", help="Overwrite existing output files and database records")
    scan_parser.add_argument("--max-seconds", type=float, default=None, help="Maximum audio duration to analyze per track")
    scan_parser.add_argument("--limit", type=int, default=None, help="Limit the number of files to process")
    scan_parser.add_argument("--keep-all-genres", action="store_true", help="Store all 400 raw genre probabilities instead of the adaptively-trimmed set")
    
    # download-model command
    download_parser = subparsers.add_parser(
        "download-model", 
        help="Download the default pre-trained Discogs-EffNet ONNX model"
    )
    download_parser.add_argument("--dest", type=str, default=None, help="Destination path for ONNX file")
    
    # sync-plex command
    sync_parser = subparsers.add_parser(
        "sync-plex",
        help="Connect to Plex server and pull play counts, user ratings, and track details to local database"
    )
    sync_parser.add_argument("--url", type=str, default=None, help="Optional Plex server URL override")
    sync_parser.add_argument("--token", type=str, default=None, help="Optional Plex Token override")
    
    # sync-new command
    sync_new_parser = subparsers.add_parser(
        "sync-new",
        help="Find tracks added to Plex since last sync, resolve SMB paths, encode embeddings, predict 400 genres, and update database"
    )
    sync_new_parser.add_argument("--url", type=str, default=None, help="Optional Plex server URL override")
    sync_new_parser.add_argument("--token", type=str, default=None, help="Optional Plex Token override")
    
    # predict-genres command
    predict_parser = subparsers.add_parser(
        "predict-genres",
        help="Run 400 Discogs genre/style prediction model across database tracks and populate tall table"
    )
    predict_parser.add_argument("--limit", type=int, default=None, help="Limit number of tracks to process")
    predict_parser.add_argument("--force", action="store_true", help="Recalculate predictions for tracks already populated")
    predict_parser.add_argument("--keep-all-genres", action="store_true", help="Store all 400 raw genre probabilities instead of the adaptively-trimmed set")

    # migrate-labels command (consolidate genre + style + mood into track_labels)
    migrate_parser = subparsers.add_parser(
        "migrate-labels",
        help="Populate embedding.track_labels from discogs genres + style/mood tagger OOF parquets"
    )
    migrate_parser.add_argument("--style-parquet", type=str, default="./models/taggers/predictions_style_oof.parquet", help="Style tagger OOF parquet")
    migrate_parser.add_argument("--mood-parquet", type=str, default="./models/taggers/predictions_mood_curated_oof.parquet", help="Curated mood tagger OOF parquet")
    migrate_parser.add_argument("--frac", type=float, default=None, help="Adaptive keep threshold frac*top1 for style/mood (default 0.85)")
    migrate_parser.add_argument("--cap", type=int, default=None, help="Max labels per track for style/mood (default 5)")
    migrate_parser.add_argument("--drop-old", action="store_true", help="After migrating, DROP discogs_genre_predictions and track_tag_predictions")

    # tag-labels-report command (read-only; safe on partially-synced data)
    tag_report_parser = subparsers.add_parser(
        "tag-labels-report",
        help="Report weak-label coverage (inherited artist/album styles & moods) to help pick min-support"
    )
    tag_report_parser.add_argument("--min-support", type=int, default=None, help="Minimum positive tracks per tag to keep it")

    # train-tagger command (wait until the taxonomy sync has finished)
    train_tagger_parser = subparsers.add_parser(
        "train-tagger",
        help="Train the per-track style/mood linear probe from inherited artist/album tags"
    )
    train_tagger_parser.add_argument("tag_type", choices=["style", "mood"], help="Which tag family to train")
    train_tagger_parser.add_argument("--min-support", type=int, default=None, help="Minimum positive tracks per tag to keep it")
    train_tagger_parser.add_argument("--C", type=float, default=1.0, help="Inverse L2 regularization strength for logistic regression")

    # predict-tags command (requires a trained tagger)
    predict_tags_parser = subparsers.add_parser(
        "predict-tags",
        help="Score all tracks with the trained tagger and store per-track style/mood probabilities"
    )
    predict_tags_parser.add_argument("tag_type", choices=["style", "mood"], help="Which tag family to predict")
    predict_tags_parser.add_argument("--min-prob", type=float, default=None, help="Only store probabilities at or above this floor")
    predict_tags_parser.add_argument("--to-db", action="store_true", help="Write to the database. Default: write a Parquet file for validation first")
    predict_tags_parser.add_argument("--out", type=str, default=None, help="Parquet output path (default: models/taggers/predictions_<tag_type>.parquet)")

    # playlist command (generate discovery playlist with diversity and recency rules, push to Plex)
    playlist_parser = subparsers.add_parser(
        "playlist",
        help="Generate a discovery playlist based on mood, style, genre, or seed song with diversity constraints, and push to Plex"
    )
    playlist_parser.add_argument("--prompt", "-p", type=str, default=None, help="Freeform seed prompt (song title, mood, style, or genre)")
    playlist_parser.add_argument("--seed-song", "-s", type=str, default=None, help="Specific seed song title or artist - title")
    playlist_parser.add_argument("--mood", "-m", type=str, default=None, help="Specific AllMusic mood tag filter")
    playlist_parser.add_argument("--style", type=str, default=None, help="Specific AllMusic style tag filter")
    playlist_parser.add_argument("--genre", "-g", type=str, default=None, help="Specific Discogs genre tag filter")
    playlist_parser.add_argument("--count", "-c", type=int, default=50, help="Target number of tracks in playlist (40-60, default: 50)")
    playlist_parser.add_argument("--min-artists", type=int, default=10, help="Minimum unique artists required in playlist (default: 10)")
    playlist_parser.add_argument("--artist-window", type=int, default=4, help="Sliding window size preventing artist repeats (default: 4)")
    playlist_parser.add_argument("--album-window", type=int, default=10, help="Sliding window size preventing album repeats (default: 10)")
    playlist_parser.add_argument("--title", type=str, default=None, help="Title for the playlist in Plex")
    playlist_parser.add_argument("--upload", action="store_true", default=True, help="Push generated playlist to Plex Server (default: True)")
    playlist_parser.add_argument("--no-upload", action="store_false", dest="upload", help="Do not upload to Plex (preview only)")
    playlist_parser.add_argument("--overwrite", action="store_true", default=True, help="Overwrite existing Plex playlist with same title if present (default: True)")
    playlist_parser.add_argument("--ignore-play-history", action="store_true", help="Bypass 6-month recency and <3 play count restrictions")
    playlist_parser.add_argument("--recent-days", type=int, default=None, help="Base the playlist on tracks played in the last N days (e.g. 14)")
    playlist_parser.add_argument("--novelty", type=str, default="similar", choices=["similar", "step_away", "different"], help="How closely the playlist should match recent listening activity (default: similar)")
    playlist_parser.add_argument("--ai-cover", action="store_true", help="Generate AI cover art for the playlist via OpenRouter (requires OPENROUTER_API_KEY)")
    playlist_parser.add_argument("--cover-image", type=str, default=None, help="Manual cover image URL or local file path (used if --ai-cover is not set or generation fails)")
    playlist_parser.add_argument("--list-moods", nargs="?", const="", type=str, default=None, help="List available AllMusic moods in database (optional filter search)")
    playlist_parser.add_argument("--list-styles", nargs="?", const="", type=str, default=None, help="List available AllMusic styles in database (optional filter search)")
    playlist_parser.add_argument("--list-genres", nargs="?", const="", type=str, default=None, help="List available Discogs genres in database (optional filter search)")
    playlist_parser.add_argument("--list-all", nargs="?", const="", type=str, default=None, help="List available moods, styles, and genres in database (optional filter search)")

    # publish command (export read-path tables to parquet and upload to Cloudflare R2)
    publish_parser = subparsers.add_parser(
        "publish",
        help="Export embeddings/tracks/labels to parquet and upload to Cloudflare R2 for the cloud app"
    )
    publish_parser.add_argument("--out-dir", type=str, default=None, help="Local directory for the parquet files (default: ./data/publish)")
    publish_parser.add_argument("--no-upload", action="store_true", help="Only write parquet locally; skip the R2 upload")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "version":
        print(f"SynthDigger {APP_VERSION}")
        print(f"Catalog schema this build expects: v{SCHEMA_VERSION}")
        from music_embeddings.database import check_schema_status
        status, current, expected = check_schema_status()
        if status == "no_catalog":
            print("Catalog:  not created yet - run `synthdigger init-db`.")
        elif status == "ok":
            print(f"Catalog:  v{current} - up to date. No upgrade steps needed.")
        elif status == "needs_upgrade":
            print(f"Catalog:  v{current} - OLDER than this build (v{expected}).")
            print("          Upgrade steps are required. See the CHANGELOG:")
            print("          https://github.com/bmewing/music_discovery/blob/main/CHANGELOG.md")
        elif status == "code_outdated":
            print(f"Catalog:  v{current} - NEWER than this build (v{expected}).")
            print("          Update SynthDigger: `git pull` then `pip install -e \".[ml]\"`.")
        sys.exit(0)

    if args.command == "init-db":
        from music_embeddings.database import init_db
        try:
            init_db()
            sys.exit(0)
        except Exception as e:
            print(f"Error initializing catalog: {e}", file=sys.stderr)
            sys.exit(1)

    # Everything past here can touch the catalog; warn early if it's on a stale schema.
    _print_schema_warning_if_needed()

    if args.command == "download-model":
        dest_path = Path(args.dest or config.MODEL_PATH)
        try:
            download_default_model(dest_path)
            print(f"Success: Model downloaded to '{dest_path.resolve()}'")
            sys.exit(0)
        except Exception as e:
            print(f"Error downloading model: {e}", file=sys.stderr)
            sys.exit(1)
            
    if args.command == "sync-plex":
        from music_embeddings.plex import sync_plex_metadata
        if args.url:
            config.PLEX_URL = args.url
        if args.token:
            config.PLEX_TOKEN = args.token
            
        try:
            sync_plex_metadata()
            sys.exit(0)
        except Exception as e:
            print(f"Error during Plex metadata sync: {e}", file=sys.stderr)
            sys.exit(1)
            
    if args.command == "sync-new":
        from music_embeddings.plex import sync_incremental_plex
        if args.url:
            config.PLEX_URL = args.url
        if args.token:
            config.PLEX_TOKEN = args.token
            
        try:
            sync_incremental_plex()
            sys.exit(0)
        except Exception as e:
            print(f"Error during incremental sync: {e}", file=sys.stderr)
            sys.exit(1)
            
    if args.command == "publish":
        from music_embeddings import publish as publish_mod
        try:
            out_dir = Path(args.out_dir) if args.out_dir else None
            paths = publish_mod.publish(out_dir=out_dir, upload=not args.no_upload)
            print("\nPublished parquet files:")
            for key, path in paths.items():
                size_mb = path.stat().st_size / (1024 * 1024)
                print(f"  {key:<20} {size_mb:>7.1f} MB  {path}")
            if args.no_upload:
                print("\nUpload skipped (--no-upload). Files written locally only.")
            else:
                print(f"\nUploaded to R2 bucket '{config.R2_BUCKET}'.")
            sys.exit(0)
        except Exception as e:
            print(f"Error during publish: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "predict-genres":
        from music_embeddings.genres import process_genre_predictions
        try:
            process_genre_predictions(limit=args.limit, force=args.force, trim=not args.keep_all_genres)
            sys.exit(0)
        except Exception as e:
            print(f"Error predicting genres: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "migrate-labels":
        from music_embeddings.labels import migrate_to_track_labels, TAGGER_SELECTION
        from music_embeddings.genre_selection import SelectionParams
        try:
            params = SelectionParams(
                min_conf=TAGGER_SELECTION.min_conf,
                frac=args.frac if args.frac is not None else TAGGER_SELECTION.frac,
                floor=TAGGER_SELECTION.floor,
                cap=args.cap if args.cap is not None else TAGGER_SELECTION.cap,
            )
            migrate_to_track_labels(
                style_parquet=args.style_parquet,
                mood_parquet=args.mood_parquet,
                params=params,
                drop_old=args.drop_old,
            )
            sys.exit(0)
        except Exception as e:
            print(f"Error migrating labels: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "tag-labels-report":
        from music_embeddings import tagger
        try:
            kwargs = {} if args.min_support is None else {"min_support": args.min_support}
            tagger.report_label_coverage(**kwargs)
            sys.exit(0)
        except Exception as e:
            print(f"Error generating tag-labels report: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "train-tagger":
        from music_embeddings import tagger
        try:
            kwargs = {"C": args.C}
            if args.min_support is not None:
                kwargs["min_support"] = args.min_support
            tagger.train_tagger(args.tag_type, **kwargs)
            sys.exit(0)
        except Exception as e:
            print(f"Error training tagger: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "predict-tags":
        from music_embeddings import tagger
        from pathlib import Path as _Path
        try:
            if args.to_db:
                # Adaptive selection -> unified track_labels (source per tag_type)
                tagger.predict_and_store(args.tag_type)
            else:
                out = _Path(args.out) if args.out else None
                kwargs = {} if args.min_prob is None else {"min_store_prob": args.min_prob}
                tagger.predict_to_parquet(args.tag_type, out_path=out, **kwargs)
            sys.exit(0)
        except Exception as e:
            print(f"Error predicting tags: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "playlist":
        from music_embeddings import playlist as pl_mod
        try:
            # Handle listing flags if requested
            if args.list_moods is not None:
                pl_mod.print_available_labels(source="allmusic mood", filter_query=args.list_moods)
                sys.exit(0)
            if args.list_styles is not None:
                pl_mod.print_available_labels(source="allmusic style", filter_query=args.list_styles)
                sys.exit(0)
            if args.list_genres is not None:
                pl_mod.print_available_labels(source="discogs genre", filter_query=args.list_genres)
                sys.exit(0)
            if args.list_all is not None:
                pl_mod.print_available_labels(source=None, filter_query=args.list_all)
                sys.exit(0)

            if not any([args.prompt, args.seed_song, args.mood, args.style, args.genre, args.recent_days]):
                print("Error: Please specify at least one seed, filter, or listing option: --prompt (-p), --seed-song (-s), --mood (-m), --style, --genre (-g), --recent-days, --list-moods, --list-styles, or --list-genres", file=sys.stderr)
                sys.exit(1)

            print("\nGenerating discovery playlist with recency and diversity constraints...")
            tracks, meta = pl_mod.generate_playlist(
                prompt=args.prompt,
                seed_song=args.seed_song,
                mood=args.mood,
                style=args.style,
                genre=args.genre,
                count=args.count,
                min_artists=args.min_artists,
                artist_window=args.artist_window,
                album_window=args.album_window,
                ignore_play_history=args.ignore_play_history,
                recent_days=args.recent_days,
                novelty=args.novelty
            )

            # Determine title
            if args.title:
                pl_title = args.title
            elif meta.get('clever_title'):
                pl_title = meta['clever_title']
            else:
                seed_val = args.prompt or args.seed_song or args.mood or args.style or args.genre or (f"Recent Mix ({args.novelty})" if args.recent_days else "Mix")
                pl_title = f"Discovery - {seed_val.title()}"

            print(f"\n==================================================")
            print(f" Playlist Generated Successfully!")
            print(f" Title: '{pl_title}'")
            print(f" Target/Seed: {meta['description']}")
            print(f" Total Tracks: {len(tracks)} (Target: {meta['target_count']})")
            print(f" Unique Artists: {meta['unique_artists']} (Requirement: >= {args.min_artists})")
            print(f" Unique Albums: {meta['unique_albums']}")
            print(f" Recency Filter: {'Disabled' if meta['ignore_play_history'] else '< 3 plays OR unplayed in last 6 months'}")
            print(f"==================================================\n")

            print(f"{'#':>2} | {'Artist':<25} | {'Title':<30} | {'Album':<25} | {'Sim':<5} | {'Plays':<5}")
            print("-" * 100)
            for idx, t in enumerate(tracks, 1):
                art = t['artist'][:24]
                tit = t['title'][:29]
                alb = t['album'][:24]
                sim = f"{t.get('sim_score', 0.0):.3f}"
                pc = t['play_count']
                print(f"{idx:2d} | {art:<25} | {tit:<30} | {alb:<25} | {sim:<5} | {pc:<5}")
            print("-" * 100)

            cover_bytes = None
            if args.ai_cover:
                print("\nGenerating AI cover art via OpenRouter...")
                cover_bytes = pl_mod.generate_ai_cover_image(meta['description'], tracks, prompt=meta.get('cover_prompt'))
                print("Cover art generated." if cover_bytes else "Cover art generation failed or skipped (check OPENROUTER_API_KEY).")

            if args.upload:
                print(f"\nUploading playlist '{pl_title}' to Plex Server...")
                res_msg = pl_mod.push_playlist_to_plex(
                    playlist_tracks=tracks,
                    title=pl_title,
                    overwrite=args.overwrite,
                    cover_image_bytes=cover_bytes,
                    cover_url=args.cover_image
                )
                print(f"\nSuccess: {res_msg}")
            else:
                print("\nUpload skipped (--no-upload passed).")

            sys.exit(0)
        except Exception as e:
            print(f"Error generating playlist: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "embed":
        audio_path = Path(args.audio_path)
        model_path = Path(args.model_path or config.MODEL_PATH)
        output_dir = Path(args.output_dir or config.OUTPUT_DIR)
        max_seconds = args.max_seconds if args.max_seconds is not None else config.MAX_SECONDS
        
        if not audio_path.exists():
            print(f"Error: Audio file not found at '{audio_path}'", file=sys.stderr)
            sys.exit(1)
            
        if not model_path.exists():
            print(
                f"Error: Model weights not found at '{model_path.resolve()}'.\n"
                f"Please download the model file first by running:\n"
                f"  python -m music_embeddings.cli download-model",
                file=sys.stderr
            )
            sys.exit(1)
            
        try:
            sha256 = calculate_sha256(audio_path)
        except Exception as e:
            print(f"Error reading audio file: {e}", file=sys.stderr)
            sys.exit(1)
            
        npy_path = output_dir / f"{sha256}.npy"
        json_path = output_dir / f"{sha256}.json"
        
        # Check if output already exists locally and in db (unless forcing)
        from music_embeddings.database import check_exists_by_hash, insert_embedding
        in_db = check_exists_by_hash(sha256)
        
        if npy_path.exists() and json_path.exists() and in_db and not args.force:
            print(f"Skipping: Outputs already exist for '{audio_path.name}' (SHA-256: {sha256}). Use --force to overwrite.")
            print(f"Output: {npy_path}")
            try:
                emb = np.load(npy_path)
                norm = np.linalg.norm(emb)
                print(f"Dimensions: {emb.shape[0]}")
                print(f"L2 norm: {norm:.4f}")
            except Exception:
                pass
            sys.exit(0)
            
        print(f"Analyzing: {audio_path.name}")
        
        try:
            embedder = MusicEmbedder(model_path)
            embedding, meta = embedder.embed_file(audio_path, max_seconds=max_seconds)
            
            # Save results (compressed npy and json metadata)
            saved_npy, saved_json = save_embedding_and_metadata(
                output_dir=output_dir,
                audio_path=audio_path,
                embedding=embedding,
                metadata_info=meta,
                model_path=model_path
            )
            
            # Save to database
            stat = audio_path.stat()
            insert_embedding(
                sha256=sha256,
                source_path=str(audio_path.resolve()),
                source_filename=audio_path.name,
                file_size=stat.st_size,
                file_mtime=stat.st_mtime,
                audio_duration=meta["duration"],
                embedding_model_name="EffnetDiscogs",
                model_filename=model_path.name,
                embedding=embedding
            )
            
            # Calculate final L2 norm
            final_norm = np.linalg.norm(embedding)
            
            print(f"\nEmbedded: {audio_path.name}")
            print(f"Dimensions: {meta['dimensions']}")
            print(f"L2 norm: {final_norm:.4f}")
            print(f"Segments analyzed: {meta['num_patches']}")
            print(f"Output: {saved_npy}")
            sys.exit(0)
            
        except Exception as e:
            print(f"Error during analysis: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "scan":
        import os
        from music_embeddings.database import check_exists_by_hash, insert_embedding, insert_track_labels_batch
        
        scan_dir = Path(args.scan_dir)
        model_path = Path(args.model_path or config.MODEL_PATH)
        output_dir = Path(args.output_dir or config.OUTPUT_DIR)
        max_seconds = args.max_seconds if args.max_seconds is not None else config.MAX_SECONDS
        
        if not scan_dir.exists():
            print(f"Error: Scanning directory not found at '{scan_dir}'", file=sys.stderr)
            sys.exit(1)
            
        if not model_path.exists():
            print(
                f"Error: Model weights not found at '{model_path.resolve()}'.\n"
                f"Please download the model file first by running:\n"
                f"  python -m music_embeddings.cli download-model",
                file=sys.stderr
            )
            sys.exit(1)
            
        # Find all audio files recursively, skipping hidden/macOS dot-under files
        print(f"Scanning directory recursively: '{scan_dir.resolve()}'")
        audio_files = []
        
        # Select walking mechanism: UNC paths require smbclient.walk to bypass Windows SMB signature bugs
        scan_dir_str = str(scan_dir)
        if scan_dir_str.startswith("\\\\"):
            import smbclient
            walker = smbclient.walk(scan_dir_str)
        else:
            import os
            walker = os.walk(scan_dir)
            
        for root, dirs, files in walker:
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                if file.startswith('.'):
                    continue
                path = Path(root) / file
                if path.suffix.lower() in {'.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg'}:
                    audio_files.append(path)
            
            # Optimization: stop walking once we've collected enough files to satisfy the limit
            if args.limit and len(audio_files) >= args.limit:
                break
                    
        total_files = len(audio_files)
        print(f"Found {total_files} audio files.")
        
        if args.limit:
            audio_files = audio_files[:args.limit]
            print(f"Applying limit: Processing first {len(audio_files)} files.")
            
        if not audio_files:
            print("No audio files found. Exiting.")
            sys.exit(0)
            
        # Initialize the embedder once
        try:
            embedder = MusicEmbedder(model_path)
        except Exception as e:
            print(f"Error loading model: {e}", file=sys.stderr)
            sys.exit(1)
            
        success_count = 0
        skipped_count = 0
        error_count = 0
        
        for idx, file_path in enumerate(audio_files, 1):
            print(f"[{idx}/{len(audio_files)}] Processing: {file_path.name}")
            try:
                # 1. Calculate file hash
                sha256 = calculate_sha256(file_path)
                
                # 2. Check if hash exists in db or locally (and not forcing)
                local_npy = output_dir / f"{sha256}.npy"
                local_json = output_dir / f"{sha256}.json"
                
                in_db = check_exists_by_hash(sha256)
                local_exists = local_npy.exists() and local_json.exists()
                
                if (in_db or local_exists) and not args.force:
                    print(f"  -> Already analyzed (SHA-256: {sha256}). Skipping.")
                    skipped_count += 1
                    continue
                    
                # 3. Generate embedding and genre predictions
                embedding, meta, genre_probs = embedder.embed_and_predict_file(file_path, max_seconds=max_seconds)
                
                # Determine relative source path starting from the name of the scanned directory
                try:
                    relative_source_path = str(file_path.relative_to(scan_dir.parent))
                except ValueError:
                    relative_source_path = str(file_path.resolve())
                
                # 4. Save locally
                save_embedding_and_metadata(
                    output_dir=output_dir,
                    audio_path=file_path,
                    embedding=embedding,
                    metadata_info=meta,
                    model_path=model_path,
                    source_path=relative_source_path
                )
                
                # 5. Save to database
                stat = file_path.stat()
                insert_embedding(
                    sha256=sha256,
                    source_path=relative_source_path,
                    source_filename=file_path.name,
                    file_size=stat.st_size,
                    file_mtime=stat.st_mtime,
                    audio_duration=meta["duration"],
                    embedding_model_name="EffnetDiscogs",
                    model_filename=model_path.name,
                    embedding=embedding
                )
                
                # 6. Save genre labels to unified track_labels (adaptively trimmed unless --keep-all-genres)
                from music_embeddings.genre_selection import selected_prob_rows
                from music_embeddings.labels import SOURCE_DISCOGS_GENRE
                if args.keep_all_genres:
                    selected = [(sha256, g, p) for g, p in genre_probs.items()]
                else:
                    selected = selected_prob_rows(sha256, genre_probs)
                genre_rows = [(sha, label, SOURCE_DISCOGS_GENRE, prob) for sha, label, prob in selected]
                insert_track_labels_batch(genre_rows)
                
                print(f"  -> Success: {meta['num_patches']} segments, duration: {meta['duration']:.1f}s")
                success_count += 1
                
            except Exception as e:
                print(f"  -> Error processing '{file_path.name}': {e}", file=sys.stderr)
                error_count += 1
                
        print(f"\nScan finished: {success_count} succeeded, {skipped_count} skipped, {error_count} failed.")
        sys.exit(0 if error_count == 0 else 1)

if __name__ == "__main__":
    main()
