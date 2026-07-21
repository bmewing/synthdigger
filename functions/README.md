# DigitalOcean Functions backend

The cloud API: one Python Function per endpoint, served under `/api/music/<name>` behind App Platform's ingress (see `.do/app.yaml.example`). Each Function's handler lives in `packages/music/<name>/__main__.py`; shared logic comes from the `music_embeddings` package, vendored into `lib/` at build time.

All endpoints except the auth trio require a valid session cookie (see [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md#how-authentication-works)).

| Function | What it does |
|---|---|
| `plex-auth-start` | Creates a plex.tv PIN and returns the `app.plex.tv` sign-in URL. |
| `plex-auth-poll` | Polls the PIN; on success resolves the user's connection to *your* server (filtered by `PLEX_SERVER_MACHINE_ID`) and mints the HMAC session cookie. |
| `whoami` | Returns the signed-in identity, or 401. |
| `logout` | Clears the session cookie. |
| `generate` | The core endpoint: runs `generate_playlist()` against the parquet snapshot (seed song / mood / style / genre / freeform prompt / recent listening + novelty). Skips the slow creative call — that's `creative`'s job. |
| `creative` | Generates the playlist title + cover-art prompt via DeepSeek. Fired by the client *after* `generate` returns, so a slow/failed AI call never blocks the tracklist. |
| `cover` | Generates AI cover art via OpenRouter, stores the PNG in R2 under `covers/`, returns a presigned URL. |
| `push` | Creates/overwrites the playlist on your Plex server *as the signed-in user*, uploads the cover, records history. |
| `seed-search` | Typeahead search for seed tracks (title/artist/rating-key/sha256). |
| `label-search` | Search available mood/style/genre labels. |
| `autocomplete-data` | Returns the full label + track-title vocabulary in one shot, so the frontend loads typeahead data once instead of hitting a Function per keystroke. |
| `history-list` | Lists the signed-in user's pushed playlists (stored as `history/<plex_user_id>.json` in R2). |
| `history-refresh` | Re-generates a saved playlist with its original parameters and re-pushes it. |
| `history-delete` | Deletes a saved playlist from Plex and from history. |

Timeouts/memory per Function are set in `project.yml`; env vars flow from the App Platform spec through `project.yml`'s `environment:` block into `music_embeddings.config`.

## The vendored `lib/`

`lib/music_embeddings` and `lib/plexapi` are build artifacts (gitignored), not sources:

* **App Platform build:** `lib/build.sh` runs during deploy — copies `src/music_embeddings` and fetches a pinned PlexAPI sdist. This is why your *fork* must contain any package changes you want deployed.
* **Local iteration:** `python functions/sync_lib.py` does the same thing on your machine.

Each Function's `.include` file lists what gets bundled into its deploy package (its `__main__.py` plus `lib/music_embeddings`). DO enforces a 48MB package limit, which is why heavyweight deps (pyarrow, sklearn) are never imported on the cloud path.

## Local dev server

`local_dev_server.py` emulates DO's event/response contract at `http://localhost:8787/api/music/<name>`, so the whole stack runs locally against parquet files in `LOCAL_PARQUET_DIR` — no R2, no DO account. See [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md#local-development).
