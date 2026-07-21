# Deploying the web app

This walks a fresh fork from "local index built" to "web app live on your own domain." It assumes you've completed the local pipeline in the [README](../README.md) — the cloud tier serves a *published snapshot* of that index, so there's nothing to deploy until the catalog exists.

**What you'll need:**

* A GitHub fork of this repository (the deploy builds from *your* fork — see [Why a fork](#why-a-fork-not-just-the-cli)).
* A [Cloudflare](https://dash.cloudflare.com/) account (R2 has a generous free tier).
* A [DigitalOcean](https://cloud.digitalocean.com/) account and the [`doctl`](https://docs.digitalocean.com/reference/doctl/how-to/install/) CLI.
* Plex **Remote Access** enabled on your server (the cloud pushes playlists to it via its public `plex.direct` address).

---

## 1. Create the R2 bucket and publish the snapshot

1. In the Cloudflare dashboard: **R2 → Create bucket** (the default name this project expects is `music-discovery`; anything works if you set `R2_BUCKET`).
2. **R2 → Manage API tokens → Create API token** with read/write access to that bucket. Note the Access Key ID, Secret Access Key, and your Account ID.
3. Fill in `.env`:

   ```
   R2_ACCOUNT_ID=...
   R2_ACCESS_KEY_ID=...
   R2_SECRET_ACCESS_KEY=...
   R2_BUCKET=music-discovery
   ```

4. Publish:

   ```bash
   python -m music_embeddings.cli publish
   ```

   This exports and uploads three parquet files — `embeddings.parquet`, `tracks.parquet`, `labels.parquet` — which are the *entire* read surface of the cloud app. Verify all three appear in the bucket. (The bucket also accumulates `covers/` PNGs and per-user `history/*.json` at runtime.)

## 2. Collect the two cloud secrets

* **`PLEX_SERVER_MACHINE_ID`** — your server's stable `machineIdentifier`. Open
  `https://plex.tv/api/v2/resources?X-Plex-Token=YOUR_TOKEN` in a browser and copy the
  `clientIdentifier` of your server entry. The Functions use it to pick *your* server
  among all servers a signed-in account can see.
* **`SESSION_SECRET_KEY`** — signs the session cookie. Generate one:

  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

## 3. Fill in the app spec

```bash
cp .do/app.yaml.example .do/app.yaml   # .do/app.yaml is gitignored - real secrets live only here
```

Edit `.do/app.yaml`:

* Set both `github.repo` fields to your fork (`you/music_discovery`) and `branch` to the branch you deploy from (`main`).
* Fill every `value: ""` under `envs` from your `.env`. `OPENROUTER_API_KEY` may stay empty — titles and cover art are skipped gracefully.

The spec deploys two components under one domain: the static frontend at `/` and the Functions at `/api/*`, which keeps every browser call same-origin (no CORS in production).

You'll also need to authorize DigitalOcean's GitHub app for your fork the first time: App Platform → Settings → GitHub, or just let `doctl apps create` walk you through the OAuth prompt.

## 4. Create the app

```bash
doctl auth init                          # paste a DO API token
doctl apps create --spec .do/app.yaml
doctl apps list                          # note the app ID and default ondigitalocean.app URL
```

The Functions build runs `functions/lib/build.sh`, which vendors `src/music_embeddings` (and a pinned PlexAPI) into the deploy package at build time.

Day-2 operations:

* **Code changes** deploy automatically on push to the tracked branch (`deploy_on_push: true`).
* **Spec/env changes** (rotated secrets, new vars) are *not* picked up from git — the real `app.yaml` is gitignored. Apply them with:

  ```bash
  doctl apps update <app-id> --spec .do/app.yaml
  ```

* **Logs:** `doctl apps logs <app-id> --type run` (add `--component api` for the Functions).

## 5. Optional: custom domain

App Platform → your app → Settings → Domains, add e.g. `music.example.com` and point a CNAME at the app's `ondigitalocean.app` hostname. TLS is automatic.

## 6. Keep the snapshot fresh

Play counts and new tracks only reach the cloud when `publish` runs again. Schedule it on the machine that runs the pipeline:

* **Windows:** Task Scheduler → run `scripts/refresh_plex_r2.ps1` daily (sync + publish) and `scripts/refresh_style_mood_r2.ps1` monthly (re-score style/mood tags + publish).
* **Linux/macOS:** cron the equivalent commands (listed at the top of each script).

---

## How authentication works

There are no accounts to manage. The app leans entirely on Plex:

1. The browser calls `plex-auth-start`, which creates a **plex.tv PIN** and returns an `app.plex.tv` link.
2. The user signs in to Plex in a new tab; the frontend polls `plex-auth-poll`.
3. On success, the Function looks up the account's servers on plex.tv, keeps only the one matching `PLEX_SERVER_MACHINE_ID`, and tries its non-relay `plex.direct` connections until one works. **If the account has no access to your server, sign-in fails** — that's the entire access-control model.
4. The resolved `{plex_url, plex_token}` and identity are sealed into an HMAC-signed, HttpOnly, 30-day session cookie (`SESSION_SECRET_KEY`). Every other Function validates that cookie; `push` uses the token inside it, so playlists are created *as the signed-in user*, not as you.

What's publicly reachable: the static frontend and the auth endpoints. Everything else returns 401 without a valid session. The R2 bucket is private — Functions access it with credentials, and cover images are served via short-lived presigned URLs. What a signed-in user can see: track/artist/album names, play counts, and labels from the published snapshot — never audio files.

## Local development

Run the whole cloud stack locally with no DigitalOcean or R2 involved:

```bash
python -m music_embeddings.cli publish --no-upload      # writes data/publish/*.parquet
python functions/sync_lib.py                            # vendors src/ into functions/lib/
# Windows PowerShell: $env:LOCAL_PARQUET_DIR="data/publish"  |  macOS/Linux: export LOCAL_PARQUET_DIR=data/publish
python functions/local_dev_server.py                    # serves /api/music/* on :8787
```

Then open `static-site/index.html` via any static server and set `localStorage.api_base = "http://localhost:8787/api/music"` in the browser console (see `static-site/app.js`).

## Troubleshooting

* **Function returns DO's generic error page instead of JSON** — the platform killed it at its timeout (see `functions/project.yml` limits). The `generate` path is budgeted to stay under the 30s synchronous cap; if your library is much larger than ~50k tracks, watch cold-start times.
* **403/`SignatureDoesNotMatch` from R2** — credential mismatch between what `publish` used and what the app spec has; re-check all four `R2_*` values and `doctl apps update`.
* **Sign-in succeeds but push fails** — usually Plex Remote Access: the cloud can only reach your server through a public `plex.direct` connection. Check Settings → Remote Access on the server.
* **Stale tracks/play counts in the app** — the parquet snapshot is only as fresh as the last `publish`; check your scheduled task's log in `logs/`.
