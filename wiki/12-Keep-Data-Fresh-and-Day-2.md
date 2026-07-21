# 12 · Keep Data Fresh and Day-2

The web app reads a *snapshot* of your library. New plays and new songs only show up after
you **publish** again. This page covers keeping it current, applying updates, and routine
maintenance.

## Keep play counts and new music fresh

The website only knows what your last `synthdigger publish` uploaded. To refresh:

```bash
synthdigger sync-plex        # pull latest play counts / ratings from Plex
synthdigger publish          # upload a fresh snapshot to R2
```

When you've **added new music** to Plex, analyze just the new tracks first:

```bash
synthdigger sync-new
synthdigger publish
```

### Automate it (recommended)

The repo includes ready-made refresh scripts in the `scripts/` folder:

- **`scripts/refresh_plex_r2.ps1`** — daily: sync play counts + publish.
- **`scripts/refresh_style_mood_r2.ps1`** — monthly: re-score style/mood tags + publish.

**Windows:** use **Task Scheduler** to run them on a schedule. **Mac/Linux:** use `cron` —
the equivalent commands are listed at the top of each script. Both write logs to the `logs/`
folder, so if the app looks stale you can check what the last run did.

## Applying updates to SynthDigger

When a new version is released:

```bash
git pull
pip install -e ".[ml]"
synthdigger version
```

`synthdigger version` tells you whether your catalog needs upgrade steps:

- **"up to date"** — nothing to do.
- **"OLDER than this build"** — follow the **Upgrade steps** for your version in the
  [CHANGELOG](https://github.com/bmewing/music_discovery/blob/main/CHANGELOG.md).

**For the web app**, redeploy after updating so the live site matches:
- Push the new code to your fork (this auto-redeploys the site), **and**
- if any `.do/app.yaml` values changed, apply them with
  `doctl apps update <app-id> --spec .do/app.yaml`.

After redeploying, the footer version on the site should match your local
`synthdigger version`.

## Config vs. code — the key rule

| You changed… | How it reaches the live app |
|---|---|
| Code (from `git pull` + push to fork) | **Automatic** on push (`deploy_on_push`). |
| A value in `.do/app.yaml` (secrets, env) | **Manual:** `doctl apps update <app-id> --spec .do/app.yaml`. A git push alone does **not** apply it. |

## Rotating / changing secrets

If a key is ever exposed, or you just want to rotate it:

1. Create the new key at the provider (Cloudflare R2, OpenRouter) or regenerate
   `SESSION_SECRET_KEY` (note: changing it signs everyone out).
2. Update it in both `.env` and `.do/app.yaml`.
3. If it affects publishing (R2), re-run `synthdigger publish`.
4. Apply to the live app: `doctl apps update <app-id> --spec .do/app.yaml`.

## Checking logs

```bash
doctl apps logs <app-id> --type run                 # the site
doctl apps logs <app-id> --type run --component api  # the playlist engine
```

## You're done when…

You have a refresh schedule set up (or know the two commands to run), and you know the
config-vs-code rule for updates.

**Next:** [[13 Using the Web App]]
