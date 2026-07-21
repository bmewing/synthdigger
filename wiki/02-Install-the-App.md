# 02 · Install the App

Goal: get Python and SynthDigger installed so the `synthdigger` command works. ~15 minutes.

Throughout this wiki, when you see two command blocks labeled **Windows (PowerShell)** and
**Mac/Linux**, run only the one for your system.

## Step 1 — Install Python (3.10 or newer)

1. Go to [python.org/downloads](https://www.python.org/downloads/) and install the latest
   Python 3.
2. **Windows:** on the first screen of the installer, tick **"Add python.exe to PATH"**
   before clicking Install. This matters.
3. Check it worked — open a new terminal and run:

   ```bash
   python --version
   ```

   You should see `Python 3.10` or higher. (On some Macs/Linux, use `python3` instead of
   `python`.)

## Step 2 — Install Git and get the code

1. Install Git from [git-scm.com/downloads](https://git-scm.com/downloads).
2. Download SynthDigger. If you already plan to host the web app later, do the
   [[06 Fork the Repository]] step first and clone *your* fork instead. Otherwise, to just
   try it locally:

   ```bash
   git clone https://github.com/bmewing/music_discovery.git
   cd music_discovery
   ```

   Every command from here on assumes you're **inside** this `music_discovery` folder.

## Step 3 — Create and activate a virtual environment

This keeps SynthDigger's parts tidy and separate.

```bash
python -m venv .venv
```

Then **activate** it (do this every time you open a new terminal to use SynthDigger):

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

**Mac/Linux:**
```bash
source .venv/bin/activate
```

When it's active, your prompt shows `(.venv)` at the start of the line.

> **Windows note:** if PowerShell says running scripts is disabled, run this once, then
> try activating again:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

## Step 4 — Install SynthDigger

```bash
pip install -e ".[ml]"
```

This downloads everything needed to analyze audio. It can take a few minutes and prints a
lot of text — that's normal.

## Step 5 — Confirm it worked

```bash
synthdigger version
```

You should see something like:

```
SynthDigger 1.0.3
Catalog schema this build expects: v1
Catalog:  not created yet - run `synthdigger init-db`.
```

That "not created yet" line is expected — you'll create the catalog next.

## You're done when…

`synthdigger version` prints a version number without an error.

**Next:** [[03 Connect to Plex]]
