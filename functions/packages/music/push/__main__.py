"""
DO Function: push a generated playlist to Plex.

Uses the Plex connection already resolved and embedded in the session cookie at
login time (see plex-auth-poll) - no per-request resource-discovery round trip, and
the Plex token itself never appears in the request body. If the cached connection
has gone stale (e.g. the home IP changed since login), the fix is simply to sign in
again, which re-resolves it; that's an acceptable tradeoff against a 30-day session.
"""
import logging

from music_embeddings.cloud import json_response, error_response, is_preflight, preflight_response
from music_embeddings.cloud_history import record_history
from music_embeddings.playlist import push_playlist_to_plex
from music_embeddings.webauth import get_session

logger = logging.getLogger("music_embeddings.functions.push")


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    session = get_session(event)
    if session is None:
        return error_response("Not authenticated - please sign in with Plex.", status=401, event=event)

    tracks = event.get("tracks", [])
    title = event.get("title")
    overwrite = bool(event.get("overwrite", True))
    cover_url = event.get("cover_url")
    cover_key = event.get("cover_key")
    params = event.get("params") or {}
    description = event.get("description")

    if not tracks:
        return error_response("tracks is required", status=422, event=event)
    if not title:
        return error_response("title is required", status=422, event=event)

    try:
        result_msg = push_playlist_to_plex(
            tracks,
            title,
            overwrite=overwrite,
            plex_url=session["plex_url"],
            plex_token=session["plex_token"],
            cover_url=cover_url,
        )
    except Exception as exc:
        return error_response(
            f"push failed: {exc}. If your home connection recently changed, try signing in again.",
            status=500,
            event=event,
        )

    try:
        record_history(
            session["plex_user_id"], title, params, description, len(tracks),
            cover_key=cover_key, cover_url=(cover_url if not cover_key else None),
        )
    except Exception as exc:
        # The playlist made it to Plex; losing the history entry is a lesser failure.
        logger.warning("Failed to record playlist history: %s", exc)

    return json_response({"message": result_msg}, event=event)
