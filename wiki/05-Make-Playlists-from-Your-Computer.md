# 05 · Make Playlists from Your Computer

Your library is analyzed — time to dig up playlists. These create a playlist and (by
default) save it straight to Plex.

## Try it: preview without saving

Add `--no-upload` to see a playlist printed in the terminal *without* pushing it to Plex.
Great for experimenting:

```bash
synthdigger playlist --genre "Rock" --count 30 --no-upload
```

You'll see a numbered track list with artist, title, album, and how similar each is to
what you asked for.

## The main ways to start a playlist

Pick whichever fits your mood:

```bash
# By genre, style, or mood
synthdigger playlist --genre "Jazz"
synthdigger playlist --style "Shoegaze"
synthdigger playlist --mood "Energetic"

# Around a specific song (artist - title)
synthdigger playlist --seed-song "Fleetwood Mac - Dreams"

# From a freeform idea
synthdigger playlist --prompt "rainy sunday morning"

# Based on what you've actually been playing lately…
synthdigger playlist --recent-days 14 --novelty similar      # more of the same vibe
synthdigger playlist --recent-days 14 --novelty step_away    # adjacent, a little new
synthdigger playlist --recent-days 14 --novelty different    # deliberately far afield
```

By default a playlist is **50 tracks**, favors songs you've rarely or never played (that's
the "discovery" part), and avoids repeating the same artist or album too closely together.

## Handy options

| Option | What it does |
|---|---|
| `--count 40` | How many tracks (roughly 40–60 works best). |
| `--no-upload` | Preview only; don't save to Plex. |
| `--title "My Mix"` | Name the playlist yourself. |
| `--ai-cover` | Generate an AI title + cover image (needs OpenRouter — see [[09 Optional AI Features OpenRouter]]). |
| `--ignore-play-history` | Include songs you play often, not just discoveries. |
| `--list-genres`, `--list-styles`, `--list-moods` | Show what labels exist in your library (optionally with a search word). |

Not sure what genres you have? Try:

```bash
synthdigger playlist --list-genres
```

See every option with:

```bash
synthdigger playlist --help
```

## Where do the playlists go?

Straight into Plex, under whatever title was chosen. Open Plex and you'll find them ready
to play on any device.

## You're done when…

You've generated a playlist and found it in Plex. 🎉

That's the whole local experience. If you want family/roommates to do this from their own
devices, continue to **Part B**, starting with [[06 Fork the Repository]]. Otherwise, you're
finished — enjoy.
