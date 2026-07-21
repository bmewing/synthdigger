"""
DO Function: report the current session's identity without side effects.

Lets the frontend show "Signed in as X" / a login prompt on page load, rather than
only discovering auth state when the first real action 401s.
"""
from music_embeddings.cloud import json_response, is_preflight, preflight_response
from music_embeddings.webauth import get_session


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    session = get_session(event)
    if session is None:
        return json_response({"authenticated": False}, event=event)

    return json_response({
        "authenticated": True,
        "username": session.get("plex_username"),
        "title": session.get("plex_title"),
    }, event=event)
