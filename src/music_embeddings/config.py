import os
from pathlib import Path

def load_dotenv(dotenv_path: Path = None):
    """
    Manually parses a .env file if it exists, loading key-value pairs
    into os.environ so that we don't depend on external dotenv libraries.
    Defaults to the project root's .env (NOT the CWD's) so scheduled tasks
    and shells launched from elsewhere still pick up the same config.
    """
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if not dotenv_path.exists():
            dotenv_path = Path(".env")
    if dotenv_path.exists():
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    os.environ.setdefault(key, val)

# Load configuration values
load_dotenv()

# Base directory of the music_discovery project (2 levels up from src/music_embeddings/config.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Model weight file configuration
_raw_model_path = Path(os.environ.get("MUSIC_EMBEDDING_MODEL_PATH", "./models/discogs-effnet-bsdynamic-1.onnx"))
MODEL_PATH = _raw_model_path if _raw_model_path.is_absolute() else (PROJECT_ROOT / _raw_model_path).resolve()

# Output directory for saved embeddings and JSON metadata
_raw_output_dir = Path(os.environ.get("MUSIC_EMBEDDING_OUTPUT_DIR", "./data/embeddings"))
OUTPUT_DIR = _raw_output_dir if _raw_output_dir.is_absolute() else (PROJECT_ROOT / _raw_output_dir).resolve()


# Audio processing sample rate (EffNet models require 16000 Hz)
SAMPLE_RATE = int(os.environ.get("MUSIC_EMBEDDING_SAMPLE_RATE", 16000))

# Optional maximum duration in seconds to load for proof-of-concept testing
MAX_SECONDS = os.environ.get("MUSIC_EMBEDDING_MAX_SECONDS")
if MAX_SECONDS is not None:
    try:
        MAX_SECONDS = float(MAX_SECONDS)
    except ValueError:
        MAX_SECONDS = None

# Local catalog database: a single DuckDB file, no server required. Created on
# first use; safe to delete and rebuild from scratch via sync-plex/scan.
_raw_db_path = Path(os.environ.get("DUCKDB_PATH", "./data/music.duckdb"))
DUCKDB_PATH = _raw_db_path if _raw_db_path.is_absolute() else (PROJECT_ROOT / _raw_db_path).resolve()

# Plex Server integration settings
PLEX_URL = os.environ.get("PLEX_URL")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN")

# Where this machine can reach the Plex server's music files (SMB share, NFS
# mount, or a local path when the pipeline runs on the Plex host itself),
# e.g. \\nas\media or /mnt/media. Optional: when unset, Plex-reported file
# paths are tried as-is, which works when running directly on the Plex host.
MUSIC_LIBRARY_ROOT = os.environ.get("MUSIC_LIBRARY_ROOT") or None

# Comma-separated names of the top-level music folder(s) as they appear in
# your file paths (e.g. "Plex Music,Classical"). Used to align the paths Plex
# reports with the paths stored at scan time, since the two usually see the
# library through different mounts. Optional: when unset, full paths are
# compared, which only matches if both sides see identical paths.
PLEX_MUSIC_FOLDERS = [f.strip() for f in os.environ.get("PLEX_MUSIC_FOLDERS", "").split(",") if f.strip()]
# Stable machineIdentifier of the target Plex server (from plex.tv/api/v2/resources).
# Used by cloud Functions to pick the right server among an account's resources
# without ever touching the local-network PLEX_URL (unreachable from the cloud).
PLEX_SERVER_MACHINE_ID = os.environ.get("PLEX_SERVER_MACHINE_ID")

# Secret key used to HMAC-sign the cloud app's session cookie. Must be identical
# across every deployed Function (all of them need to mint or validate the same
# sessions). Any long random string works - e.g. `python -c "import secrets;
# print(secrets.token_urlsafe(32))"`.
SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY")

# OpenRouter settings - single key covers both AI title/cover-prompt generation
# (DeepSeek models, routed through OpenRouter) and AI cover art generation.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_TEXT_MODEL = os.environ.get("OPENROUTER_TEXT_MODEL")
OPENROUTER_IMAGE_MODEL = os.environ.get("OPENROUTER_IMAGE_MODEL", "black-forest-labs/flux.2-klein-4b")

# Explicit kill switch for the AI features (vibe-box freeform interpretation, AI
# title/cover-prompt generation, AI cover art) independent of whether a key is
# configured - e.g. to disable temporarily without discarding OPENROUTER_API_KEY.
DISABLE_AI_FEATURES = os.environ.get("DISABLE_AI_FEATURES", "").strip().lower() in ("1", "true", "yes")

# Cloudflare R2 (S3-compatible) object storage for publishing read-path parquet
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.environ.get("R2_BUCKET", "music-discovery")
# Endpoint is derived from the account id unless explicitly overridden
R2_ENDPOINT_URL = os.environ.get(
    "R2_ENDPOINT_URL",
    f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else None
)



