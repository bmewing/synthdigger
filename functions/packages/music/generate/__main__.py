"""
DO Function: generate a playlist against the published parquet data.

Returns only what the client needs to preview and later push (no embeddings) - the
frontend holds this tracklist and posts it back to push/creative/cover, since
Functions are stateless between invocations.
"""
from music_embeddings.cloud import get_cached_datasource, json_response, error_response, is_preflight, preflight_response
from music_embeddings.playlist import generate_playlist
from music_embeddings.webauth import get_session


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    if get_session(event) is None:
        return error_response("Not authenticated - please sign in with Plex.", status=401, event=event)

    try:
        datasource = get_cached_datasource()
        tracks, meta = generate_playlist(
            datasource=datasource,
            prompt=event.get("prompt") or None,
            seed_song=event.get("seed_song") or None,
            mood=event.get("mood") or None,
            style=event.get("style") or None,
            genre=event.get("genre") or None,
            count=int(event.get("count", 50)),
            min_artists=int(event.get("min_artists", 10)),
            artist_window=int(event.get("artist_window", 4)),
            album_window=int(event.get("album_window", 10)),
            ignore_play_history=bool(event.get("ignore_play_history", False)),
            recent_days=int(event["recent_days"]) if event.get("recent_days") else None,
            novelty=event.get("novelty", "similar"),
            include_creative=False,  # the separate `creative` Function does this - see its own timing note
        )
    except ValueError as exc:
        return error_response(str(exc), status=422, event=event)
    except Exception as exc:
        return error_response(f"generate failed: {exc}", status=500, event=event)

    slim_tracks = [
        {
            "sha256": t["sha256"],
            "rating_key": t["rating_key"],
            "artist": t["artist"],
            "album": t["album"],
            "title": t["title"],
            "sim_score": t.get("sim_score"),
            "play_count": t.get("play_count"),
        }
        for t in tracks
    ]
    return json_response({"tracks": slim_tracks, "meta": meta}, event=event)
