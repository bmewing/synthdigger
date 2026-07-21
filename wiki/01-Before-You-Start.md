# 01 · Before You Start

A quick readiness check before you install anything. Five minutes now saves headaches later.

## What you need

- [ ] **A Plex Media Server** with your music library already added, and it's running.
  SynthDigger reads from Plex — it doesn't replace it.
- [ ] **Access to your music files** from the computer you'll set this up on. Either:
  - the computer *is* your Plex server (easiest), **or**
  - it can reach the music folder over your network (a shared drive / NAS). You'll point
    SynthDigger at that location in [[03 Connect to Plex]].
- [ ] **The computer stays on** long enough to analyze your library (see time estimate
  below). It can run overnight.
- [ ] **Free disk space** for the catalog — roughly a few hundred MB for a typical library
  (it stores compact numbers per track, not audio).

You do **not** need any online accounts yet. Those come in Part B (the web app).

## How long the analysis takes

The one-time analysis in [[04 Build Your Music Index]] listens to every track. Rough guide:

| Library size | Rough analysis time (unattended) |
|---|---|
| ~1,000 tracks | 15–45 minutes |
| ~10,000 tracks | 2–6 hours |
| ~50,000+ tracks | overnight |

Exact times depend on your computer. It runs on its own — start it and walk away. You can
stop and resume; already-analyzed tracks are skipped.

## A note on comfort with the terminal

You'll be typing commands into a terminal window. That's normal and expected here — this
wiki gives you the exact text to paste for **Windows (PowerShell)** and **Mac/Linux**
separately. You won't be writing any code. If "terminal" is unfamiliar, skim the
[[Glossary and FAQ]] first.

## You're done when…

You can answer "yes" to: *my Plex server is running, I know where my music files are, and
this computer can reach them.*

**Next:** [[02 Install the App]]
