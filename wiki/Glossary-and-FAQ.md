# Glossary and FAQ

Keep this page open in a tab. When a term shows up elsewhere in the wiki, it's defined here.

## Glossary

| Term | What it means |
|---|---|
| **Terminal / command line** | A window where you type commands instead of clicking. On Windows it's **PowerShell**; on Mac it's **Terminal**. |
| **Command** | A line of text you type and press Enter to run, e.g. `synthdigger version`. |
| **`synthdigger`** | SynthDigger's command-line tool. After install you type `synthdigger …` to run things. (`python -m music_embeddings.cli …` does the exact same thing — you'll see both.) |
| **Python** | The programming language SynthDigger is written in. You install it once; you don't have to *write* any. |
| **Virtual environment (venv)** | A private sandbox for SynthDigger's Python bits so they don't clash with anything else on your computer. You "activate" it before running commands. |
| **Repository / repo** | A project's folder of code hosted on GitHub. |
| **Fork** | Your *own* copy of the repo on GitHub. The web app deploys from your fork. |
| **`.env` file** | A plain text file holding your settings and secrets (like your Plex token). SynthDigger reads it automatically. Never share it. |
| **Environment variable** | One setting inside the `.env` file, written as `NAME=value`. See [[Environment Variable Reference]]. |
| **Plex token** | A secret code that lets SynthDigger talk to your Plex server on your behalf. See [[03 Connect to Plex]]. |
| **Catalog** | The single file (`data/music.duckdb`) holding your analyzed library. Built on your computer. |
| **Embedding** | The list of numbers describing how a song *sounds*. Similar songs have similar numbers. You never see these directly. |
| **Publish** | Uploading a read-only copy of your catalog to cloud storage so the web app can read it. |
| **R2 (Cloudflare)** | Free-tier cloud storage where the published copy lives. See [[07 Sign Up Cloudflare R2]]. |
| **DigitalOcean App Platform** | The cloud host that runs the web app. See [[08 Sign Up DigitalOcean and Install doctl]]. |
| **`doctl`** | DigitalOcean's command-line tool, used to create and update the web app. |
| **PIN sign-in** | How people log into the web app: Plex shows a short code / login page instead of asking for a password on your site. |
| **Version / schema version** | The SynthDigger software version, and the version of your catalog's layout. `synthdigger version` shows both and whether an upgrade needs steps. |

## FAQ

**Do I need to know how to code?**
No. You'll copy and paste commands. Nothing needs editing beyond filling blanks in a
settings file.

**Is my music uploaded to the internet?**
No. Audio files never leave your computer. See [[Overview and How It Works]].

**What does it cost?**
Part A (your computer) is free. For the web app: GitHub and Cloudflare R2 have free tiers;
DigitalOcean typically runs a few dollars a month; OpenRouter (AI features) is optional and
pay-per-use (pennies). See the account table on [[Home]].

**Can I skip the AI features?**
Yes. Leave the OpenRouter key blank or set `DISABLE_AI_FEATURES=true`. Everything else works
the same. See [[09 Optional AI Features OpenRouter]].

**What computer do I need?**
Windows, Mac, or Linux. It should be able to reach your Plex server and your music files.
Analyzing a large library is faster with more CPU but works on modest hardware — it just
takes longer.

**How do I know if an update needs extra steps?**
Run `synthdigger version` after updating. It'll tell you if your catalog needs upgrading and
point you to the [CHANGELOG](https://github.com/bmewing/music_discovery/blob/main/CHANGELOG.md).
See [[12 Keep Data Fresh and Day-2]].

**Something went wrong.**
See [[14 Troubleshooting]].
