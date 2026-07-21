# Environment Variable Reference

Every setting that can go in your `.env` file (and, for the cloud ones, in `.do/app.yaml`).
"Where do I get this" points you to the page that explains it.

> **Never share your `.env` or `.do/app.yaml`.** They hold secrets. Only the `.example`
> templates (with blank values) belong on GitHub.

## Local pipeline (needed to analyze your library)

| Setting | Required? | What it is / where to get it |
|---|---|---|
| `PLEX_URL` | **Yes** | Your Plex server address, e.g. `http://localhost:32400`. See [[03 Connect to Plex]]. |
| `PLEX_TOKEN` | **Yes** | Your Plex auth token. See [[03 Connect to Plex]]. |
| `DUCKDB_PATH` | No | Where the catalog file lives. Default `./data/music.duckdb`. |
| `MUSIC_LIBRARY_ROOT` | No | Where *this computer* reaches the music files (network share/mount). Leave unset if running on the Plex host. See [[03 Connect to Plex]]. |
| `PLEX_MUSIC_FOLDERS` | No | Top-level music folder name(s), e.g. `Plex Music,Classical`, to align paths. |
| `MUSIC_EMBEDDING_MODEL_PATH` | No | Path to the analysis model. Default `./models/...`; set by `synthdigger download-model`. |
| `MUSIC_EMBEDDING_OUTPUT_DIR` | No | Where per-track analysis files are written. Default `./data/embeddings`. |

## AI features (optional)

| Setting | Required? | What it is / where to get it |
|---|---|---|
| `OPENROUTER_API_KEY` | No | Enables AI titles + cover art. Blank = AI skipped. See [[09 Optional AI Features OpenRouter]]. |
| `OPENROUTER_TEXT_MODEL` | No | Text model override. Default `deepseek/deepseek-v4-flash`. |
| `OPENROUTER_IMAGE_MODEL` | No | Image model override. Default `black-forest-labs/flux.2-klein-4b`. |
| `DISABLE_AI_FEATURES` | No | Set to `true` to hide all AI buttons/vibe box and skip AI calls, even if a key is set. |

## Cloud web app (only if you host it — Part B)

| Setting | Required? | What it is / where to get it |
|---|---|---|
| `R2_ACCOUNT_ID` | Cloud | Cloudflare account ID. See [[07 Sign Up Cloudflare R2]]. |
| `R2_ACCESS_KEY_ID` | Cloud | R2 API token key ID. See [[07 Sign Up Cloudflare R2]]. |
| `R2_SECRET_ACCESS_KEY` | Cloud | R2 API token secret (shown once). See [[07 Sign Up Cloudflare R2]]. |
| `R2_BUCKET` | Cloud | Bucket name. Default `music-discovery`. |
| `PLEX_SERVER_MACHINE_ID` | Cloud | Your server's `clientIdentifier`, so the cloud picks the right server. See [[10 Deploy the Web App]]. |
| `SESSION_SECRET_KEY` | Cloud | Random key that signs the login cookie. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Must be the same across the deployed app. See [[10 Deploy the Web App]]. |

"Cloud" in the Required column means: required **only** if you're hosting the web app; not
needed for the local pipeline.
