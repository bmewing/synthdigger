# 14 · Troubleshooting

Common snags and how to fix them, roughly in the order you might hit them.

## Setup & local pipeline

**`synthdigger: command not found` (or not recognized)**
Your virtual environment probably isn't active. Reactivate it and try again:
- Windows: `.\.venv\Scripts\Activate.ps1`
- Mac/Linux: `source .venv/bin/activate`
You should see `(.venv)` at the start of your prompt. (You can also always use
`python -m music_embeddings.cli …` instead.)

**PowerShell won't run the activate script**
Run once, then reactivate:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**"Model weights not found" during `scan`**
You skipped the model download. Run:
```bash
synthdigger download-model
```

**`scan` finds files but `sync-plex` matches very few of them**
Plex and this computer are seeing the music at different paths. Set `MUSIC_LIBRARY_ROOT` and
`PLEX_MUSIC_FOLDERS` in `.env` — see [[03 Connect to Plex]] Step 4.

**Can't connect to Plex**
Double-check `PLEX_URL` (is it reachable from this computer? try opening it in a browser) and
that `PLEX_TOKEN` is correct and current.

## Versions & upgrades

**A warning says my catalog schema is older/newer than the build**
Run `synthdigger version` for details, then follow the **Upgrade steps** in the
[CHANGELOG](https://github.com/bmewing/music_discovery/blob/main/CHANGELOG.md). "Newer than
this build" means your code is behind — `git pull` and reinstall. See
[[12 Keep Data Fresh and Day-2]].

## Web app

**I changed a secret / env value but the live app didn't update**
Changes to `.do/app.yaml` are **not** applied by a git push. Run:
```bash
doctl apps update <app-id> --spec .do/app.yaml
```

**My custom domain stopped working after an update**
Your `.do/app.yaml` was missing the `domains:` block, so the update removed the domain.
Re-add the block (see [[11 Custom Domain]]) and run `doctl apps update` again.

**Sign-in works, but generating/pushing a playlist fails**
Usually Plex **Remote Access**: the cloud app can only reach your server over the internet.
Turn on Plex → Settings → Remote Access on the server.

**A `403` or `SignatureDoesNotMatch` error from storage**
The R2 credentials the app has don't match the ones `publish` used. Re-check all four `R2_*`
values in `.do/app.yaml`, then `doctl apps update <app-id> --spec .do/app.yaml`.

**Tracks or play counts look stale on the website**
The site only reflects your last `synthdigger publish`. Re-run `sync-plex` then `publish`
(or check your scheduled task's log in `logs/`). See [[12 Keep Data Fresh and Day-2]].

**A page shows a generic DigitalOcean error instead of a result**
The request likely hit the platform's time limit (very large libraries can push this on the
`generate` path). Check `doctl apps logs <app-id> --type run --component api`.

## Still stuck?

Check the technical docs in the repo (`README.md`, `docs/DEPLOYMENT.md`) or open an issue on
[GitHub](https://github.com/bmewing/music_discovery/issues).
