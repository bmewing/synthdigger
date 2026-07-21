"""
DO Function: regenerate a saved playlist from its original params against current
data, and re-push it to Plex under the same title.

Deliberately does not regenerate AI cover art - matches the local app's existing
design decision (see playlist.py) that a refresh shouldn't silently re-spend on
image generation every time; the previous Plex poster is left untouched.
"""
from music_embeddings.cloud import get_cached_datasource, json_response, error_response, is_preflight, preflight_response
from music_embeddings.cloud_history import get_history_entry, record_history
from music_embeddings.playlist import generate_playlist, push_playlist_to_plex
from music_embeddings.webauth import get_session


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    session = get_session(event)
    if session is None:
        return error_response("Not authenticated - please sign in with Plex.", status=401, event=event)

    title = event.get("title")
    if not title:
        return error_response("title is required", status=422, event=event)

    entry = get_history_entry(session["plex_user_id"], title)
    if entry is None:
        return error_response(f"No saved history entry titled '{title}'", status=404, event=event)

    try:
        datasource = get_cached_datasource()
        tracks, meta = generate_playlist(datasource=datasource, include_creative=False, **entry.get("params", {}))
    except ValueError as exc:
        return error_response(str(exc), status=422, event=event)
    except Exception as exc:
        return error_response(f"history-refresh (generate) failed: {exc}", status=500, event=event)

    try:
        result_msg = push_playlist_to_plex(
            tracks,
            title,
            overwrite=True,
            plex_url=session["plex_url"],
            plex_token=session["plex_token"],
        )
    except Exception as exc:
        return error_response(f"history-refresh (push) failed: {exc}", status=500, event=event)

    try:
        record_history(session["plex_user_id"], title, entry.get("params", {}), meta.get("description"), len(tracks))
    except Exception:
        pass

    return json_response({"message": result_msg, "track_count": len(tracks)}, event=event)
