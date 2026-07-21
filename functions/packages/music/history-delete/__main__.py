"""DO Function: delete a saved playlist - removes it from Plex, then forgets its history entry."""
from music_embeddings.cloud import json_response, error_response, is_preflight, preflight_response
from music_embeddings.cloud_history import delete_history_entry
from music_embeddings.playlist import delete_playlist_from_plex
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

    try:
        delete_playlist_from_plex(title, plex_url=session["plex_url"], plex_token=session["plex_token"])
    except Exception as exc:
        return error_response(
            f"Could not remove '{title}' from Plex: {exc}. History entry was left in place.",
            status=500,
            event=event,
        )

    try:
        deleted = delete_history_entry(session["plex_user_id"], title)
    except Exception as exc:
        return error_response(f"history-delete failed: {exc}", status=500, event=event)

    return json_response({"deleted": deleted}, event=event)
