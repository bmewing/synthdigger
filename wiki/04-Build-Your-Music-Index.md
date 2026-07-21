# 04 · Build Your Music Index

Goal: analyze your whole library so SynthDigger knows what everything sounds like. This is
the **biggest one-time step** — mostly unattended. Review the time estimate in
[[01 Before You Start]].

> **Tip:** these commands run in order. If you close the terminal, just reactivate the
> virtual environment (`.\.venv\Scripts\Activate.ps1` or `source .venv/bin/activate`) and
> continue. Steps skip work that's already done, so it's safe to stop and resume.

## Step 1 — Download the analysis model

This is the "ears" — a pre-trained model that listens to audio. One download, ~a few
hundred MB.

```bash
synthdigger download-model
```

## Step 2 — Analyze your audio files

Point SynthDigger at your music folder. Use the path this computer sees:

**Windows (PowerShell):**
```powershell
synthdigger scan "D:\Music"
```

**Mac/Linux:**
```bash
synthdigger scan "/path/to/your/music"
```

This is the long part. It prints progress like `[1234/50000] Processing: song.flac`. Let it
run. Want to test the waters first? Add `--limit 50` to only do the first 50 tracks.

## Step 3 — Pull in play history from Plex

Now bring over titles, artists, albums, ratings, and play counts, and match them to the
analyzed audio:

```bash
synthdigger sync-plex
```

## Step 4 — Add genre, style, and mood labels

These let you ask for playlists by genre/style/mood. Run them in order:

```bash
synthdigger predict-genres                 # 400-way genre labels
synthdigger train-tagger style             # learn style tags from your library
synthdigger train-tagger mood              # learn mood tags
synthdigger predict-tags style --to-db     # apply style tags to every track
synthdigger predict-tags mood --to-db      # apply mood tags to every track
```

Each prints progress and a summary. If one reports very few labels, that's usually fine for
a smaller or genre-narrow library.

## Keeping it up to date later

When you add new music to Plex, you don't redo everything — just run:

```bash
synthdigger sync-new
```

It finds tracks added since last time, analyzes and labels only those. (For the web app,
you then re-**publish** — see [[12 Keep Data Fresh and Day-2]].)

## You're done when…

`synthdigger scan`, `sync-plex`, and the label commands have all finished without errors.
Your catalog now knows your library. Time to make something with it.

**Next:** [[05 Make Playlists from Your Computer]]
