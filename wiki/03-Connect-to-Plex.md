# 03 · Connect to Plex

Goal: tell SynthDigger how to reach your Plex server by filling in a settings file. ~10 minutes.

## Step 1 — Create your settings file

In the `music_discovery` folder, make a copy of the example settings file and name it
`.env`:

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**Mac/Linux:**
```bash
cp .env.example .env
```

Open `.env` in any plain text editor (Notepad, TextEdit, VS Code). Every setting is a line
like `NAME=value`. You'll fill in a couple of them. Lines starting with `#` are notes.

> **Keep `.env` private.** It holds secrets. It's already set up to stay off GitHub — never
> paste its contents anywhere public.

## Step 2 — Set your Plex server address

Find the line `PLEX_URL=` and set it to your server's address.

- If SynthDigger is running **on the same computer** as Plex, the default is usually fine:
  ```
  PLEX_URL=http://localhost:32400
  ```
- If Plex is on a **different machine** on your network, use its local IP, e.g.:
  ```
  PLEX_URL=http://192.168.1.50:32400
  ```

## Step 3 — Get your Plex token

A **token** is a secret code that lets SynthDigger use Plex as you. To find yours:

**The easy way (from any Plex web page):**
1. Sign in at [app.plex.tv](https://app.plex.tv/) and open any track or album.
2. Click the **⋯ (More)** menu → **Get Info** → **View XML**.
3. A new browser tab opens with a long web address. At the very end of it you'll see
   `X-Plex-Token=…`. Copy the value after the `=`.

Plex documents this here: [Finding an authentication token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

Paste it into `.env`:

```
PLEX_TOKEN=paste-your-token-here
```

## Step 4 — (Only if your music is on a network share)

Skip this if SynthDigger runs directly on the Plex server.

If this computer reaches your music through a shared drive or NAS, Plex and SynthDigger may
see the files at different paths. Set these so they can be matched up:

```
# Where THIS computer sees the music (examples):
MUSIC_LIBRARY_ROOT=\\nas\media        # Windows network share
# MUSIC_LIBRARY_ROOT=/mnt/media       # Mac/Linux mount

# The top-level music folder name(s) as they appear in your paths:
PLEX_MUSIC_FOLDERS=Plex Music
```

If you're unsure, leave them commented out for now and revisit if track-matching looks off
in the next step (see [[14 Troubleshooting]]).

## Step 5 — Test the connection

Create the (empty) catalog file, which also confirms your setup loads correctly:

```bash
synthdigger init-db
```

You should see `Success: Initialized ... catalog`. Then confirm the Plex settings are being
read:

```bash
synthdigger version
```

The "Catalog" line should now say **v1 - up to date**.

## You're done when…

`synthdigger init-db` succeeds and your `.env` has a real `PLEX_URL` and `PLEX_TOKEN`.

**Next:** [[04 Build Your Music Index]]
