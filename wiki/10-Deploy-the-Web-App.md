# 10 · Deploy the Web App

This puts the website live. You'll: publish your library to R2, gather two more secrets,
fill in one config file, and create the app. Budget ~30–45 minutes the first time.

**Before you start**, make sure you've finished [[07 Sign Up Cloudflare R2]] and
[[08 Sign Up DigitalOcean and Install doctl]], and that Plex **Remote Access** is enabled on
your server (Plex → Settings → Remote Access). The cloud app reaches your Plex over the
internet, so this is required.

## Step 1 — Publish your library to R2

With the `R2_*` values in your `.env` (from [[07 Sign Up Cloudflare R2]]), upload a
read-only snapshot:

```bash
synthdigger publish
```

This uploads three files (`embeddings.parquet`, `tracks.parquet`, `labels.parquet`) — the
entire read surface of the web app. When it finishes, check your `music-discovery` bucket in
Cloudflare and confirm the three files are there.

## Step 2 — Collect two more secrets

Add these to `.env`:

1. **`PLEX_SERVER_MACHINE_ID`** — your server's stable ID, so the cloud picks the right
   server. Open this in a browser (replace `YOUR_TOKEN` with your Plex token from
   [[03 Connect to Plex]]):
   ```
   https://plex.tv/api/v2/resources?X-Plex-Token=YOUR_TOKEN
   ```
   Find your server in the list and copy its `clientIdentifier` value.
   ```
   PLEX_SERVER_MACHINE_ID=your-server-client-identifier
   ```

2. **`SESSION_SECRET_KEY`** — signs the login cookie. Generate a random one:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Paste the output:
   ```
   SESSION_SECRET_KEY=the-random-string-it-printed
   ```

## Step 3 — Fill in the deploy config

Make your real deploy file from the template:

**Windows (PowerShell):**
```powershell
Copy-Item .do\app.yaml.example .do\app.yaml
```
**Mac/Linux:**
```bash
cp .do/app.yaml.example .do/app.yaml
```

Open `.do/app.yaml` in a text editor and:

- Set **both** `repo:` lines to your fork: `YOUR_USERNAME/synthdigger`.
- Fill every `value: ""` under `envs` with the matching value **from your `.env`** (the
  `R2_*` values, `PLEX_SERVER_MACHINE_ID`, `SESSION_SECRET_KEY`, and `OPENROUTER_API_KEY` if
  you set one — it can stay `""` if not).

> **Security:** `.do/app.yaml` now holds real secrets. It's already configured to stay off
> GitHub — never commit or share it. Only `.do/app.yaml.example` (all blanks) belongs in the
> repo.

## Step 4 — Create the app

```bash
doctl apps create --spec .do/app.yaml
```

The first time, DigitalOcean will ask you to authorize its GitHub app on your fork — follow
the prompt. Then:

```bash
doctl apps list
```

Note your **app ID** and the `…ondigitalocean.app` URL. Open that URL — you should see the
SynthDigger sign-in page. Sign in with your Plex account to test it end-to-end.

> **You'll see the version** in the page footer (e.g. `SynthDigger v1.0.3`). That confirms
> the backend is live and lets you tell at a glance which build is deployed.

## Important: how updates apply

- **Code changes** you push to your fork redeploy automatically.
- **Changes to `.do/app.yaml`** (new secrets, changed values) are **NOT** picked up from a
  git push — the real file is kept off GitHub. Apply those yourself with:
  ```bash
  doctl apps update <app-id> --spec .do/app.yaml
  ```

This distinction matters — see [[12 Keep Data Fresh and Day-2]].

## You're done when…

The `…ondigitalocean.app` URL loads, you can sign in with Plex, and the footer shows a
version.

**Next:** [[11 Custom Domain]] (optional), then [[12 Keep Data Fresh and Day-2]].
