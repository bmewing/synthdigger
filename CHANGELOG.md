# Changelog

All notable changes to SynthDigger are recorded here. Versions follow
[Semantic Versioning](https://semver.org/).

Two numbers matter when upgrading:

- **App version** — the software release (e.g. `1.0.3`). Shown by `synthdigger version`,
  `synthdigger --version`, and in the web app footer.
- **Catalog schema version** — the layout of your local DuckDB catalog. When a release
  bumps it, the **Upgrade steps** for that release tell you exactly what to run. `synthdigger
  version` compares your catalog's stamped schema version against what the installed build
  expects and tells you whether action is needed.

> **How to check what you're on:** run `synthdigger version`. If it says your catalog is
> *older* than the build expects, find your current app version below and follow the
> Upgrade steps for every release *after* it.

---

## [1.0.3] — SynthDigger

**Catalog schema:** v1 (unchanged from 0.1.0 — no data migration needed).

### Added
- **The project is now called SynthDigger.** The command-line tool is `synthdigger` (installed as a
  console command by `pip install -e .`); `python -m music_embeddings.cli …` still works
  and is unchanged. The web app is branded SynthDigger.
- **Versioning & upgrade detection.**
  - `synthdigger version` reports the app version, the catalog schema the build expects, and
    whether your catalog needs upgrade steps.
  - `synthdigger --version` prints the app version.
  - DB-touching commands print a one-line warning if your catalog schema is out of step
    with the installed build.
  - The local catalog now stamps its schema version (new `embedding.catalog_meta` table);
    catalogs created before this release are treated as schema v1 automatically.
  - New `version` cloud Function (`/api/music/version`) and a footer in the web app that
    shows the deployed build.
- **`synthdigger init-db`** — a friendlier alias for `python -m music_embeddings.database`.

### Upgrade steps (from 0.1.0)
1. Get the new code and reinstall so the `synthdigger` command and version metadata register:
   ```bash
   git pull
   pip install -e ".[ml]"          # local pipeline machine
   ```
2. No catalog changes — your existing `data/music.duckdb` works as-is. It will be treated
   as schema v1; the next command that opens it stamps that automatically.
3. **If you run the web app:** redeploy so the new `version` Function and the rebranded
   frontend go live. Push the updated code to your fork (auto-deploys if
   `deploy_on_push` is on), or trigger a deploy with `doctl apps create/update`. See
   [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
4. Confirm: `synthdigger version` shows `SynthDigger 1.0.3` and `Catalog: v1 - up to date`.

---

## [0.1.0]

**Catalog schema:** v1.

Initial release: local embedding pipeline (Discogs-EffNet via ONNX), Plex sync, genre /
style / mood tagging, discovery playlist generation, and the optional cloud web app
(DigitalOcean App Platform + Cloudflare R2, plex.tv PIN auth).
