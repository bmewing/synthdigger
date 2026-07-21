# SynthDigger — Setup & Owner's Guide

Welcome! This wiki walks you through setting up **SynthDigger** from scratch, even if
you've never used a command line before. Take it one page at a time and you'll end up with
a private web app your whole household can use to build great playlists from your Plex
music library.

> **New here? Read [[Overview and How It Works]] first** for a plain-English picture of
> what this does. If a word ever looks unfamiliar, the [[Glossary and FAQ]] explains it.

---

## What is SynthDigger?

SynthDigger looks at every song in your **Plex** music library, learns what each one
*sounds* like, and uses that to dig up smart playlists — "songs like this one," "something
for a rainy Sunday morning," "more of what I've been playing lately, but a little
different." You can use it two ways:

1. **On your own computer** (the `synthdigger` command-line tool). Good for trying it out
   and for the one-time job of analyzing your library.
2. **As a private website** you host, so anyone in your household can sign in with their
   own Plex account and make playlists from their phone or laptop — with an optional
   AI-generated title and cover image.

Everything runs on **your** Plex server and **your** storage. Your music is never uploaded
anywhere. (The only outside calls are optional AI features you can turn off.)

---

## Start here — the setup checklist

Follow these in order. Each page ends with a "You're done when…" checkpoint so you always
know it worked before moving on.

**Get oriented**
- [ ] [[Overview and How It Works]] — the big picture (5-minute read)
- [ ] [[Glossary and FAQ]] — plain definitions + common questions

**Part A · Set it up on your computer**
- [ ] [[01 Before You Start]] — what you need before you begin
- [ ] [[02 Install the App]] — install Python and SynthDigger
- [ ] [[03 Connect to Plex]] — get your Plex token and configure
- [ ] [[04 Build Your Music Index]] — analyze your library (the big one-time step)
- [ ] [[05 Make Playlists from Your Computer]] — your first playlists

**Part B · Put it online (optional — the household web app)**
- [ ] [[06 Fork the Repository]] — make your own copy on GitHub
- [ ] [[07 Sign Up Cloudflare R2]] — free storage for the web app
- [ ] [[08 Sign Up DigitalOcean and Install doctl]] — where the web app runs
- [ ] [[09 Optional AI Features OpenRouter]] — AI titles and cover art
- [ ] [[10 Deploy the Web App]] — put it live
- [ ] [[11 Custom Domain]] — use your own web address

**Part C · Keep it running**
- [ ] [[12 Keep Data Fresh and Day-2]] — scheduled refreshes, upgrades, maintenance
- [ ] [[13 Using the Web App]] — a guide for the people you share it with
- [ ] [[14 Troubleshooting]] — when something goes wrong

**Reference**
- [[Environment Variable Reference]] — every setting explained

---

## Accounts you'll create (all have free tiers)

You don't need any of these for Part A. They're only for the web app (Part B).

| Service | What it's for | Cost | Where |
|---|---|---|---|
| **GitHub** | Stores your copy of the code; the web app deploys from it | Free | [github.com](https://github.com/) |
| **Cloudflare** | Stores the analyzed music data the web app reads (R2) | Free tier is generous | [cloudflare.com](https://dash.cloudflare.com/) |
| **DigitalOcean** | Runs the web app itself | ~a few dollars/month | [digitalocean.com](https://cloud.digitalocean.com/) |
| **OpenRouter** | *Optional* — AI playlist titles & cover art | Pay-per-use, tiny; skippable | [openrouter.ai](https://openrouter.ai/) |
| **Plex** | You already have this — it's your music server | — | [plex.tv](https://plex.tv/) |

---

## How much time will this take?

- **Part A (computer setup):** ~30–60 minutes of hands-on time, plus a few hours of
  *unattended* time while your library is analyzed (the computer does this on its own).
- **Part B (web app):** ~1–2 hours the first time, mostly creating accounts.

You do **not** have to do Part B. Part A alone gives you a fully working playlist tool.

---

## Which version am I on?

SynthDigger is versioned so you can tell whether an update needs any extra steps. Any time
you pull a new version, run:

```bash
synthdigger version
```

It prints the software version and tells you whether your analyzed library needs any
upgrade steps. The full history (and the exact steps for each release) lives in the
[CHANGELOG](https://github.com/bmewing/synthdigger/blob/main/CHANGELOG.md). See
[[12 Keep Data Fresh and Day-2]] for how upgrades work.
