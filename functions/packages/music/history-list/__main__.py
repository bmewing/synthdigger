"""DO Function: list the current account's saved playlist history."""
from music_embeddings.cloud import json_response, error_response, is_preflight, preflight_response
from music_embeddings.cloud_history import load_history
from music_embeddings.webauth import get_session


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    session = get_session(event)
    if session is None:
        return error_response("Not authenticated - please sign in with Plex.", status=401, event=event)

    try:
        entries = load_history(session["plex_user_id"])
    except Exception as exc:
        return error_response(f"history-list failed: {exc}", status=500, event=event)

    return json_response({"history": entries}, event=event)
