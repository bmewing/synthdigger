"""
DO Function: regenerate a saved playlist from its original params against current
data, and re-push it to Plex under the same title.

Does not regenerate AI cover art (a refresh shouldn't silently re-spend on image
generation every time) - but a `push`-time overwrite deletes and recreates the Plex
playlist object (see push_playlist_to_plex), which would otherwise take the old
poster down with it. So instead, if the saved history entry has a cover_key (an
R2-hosted AI-generated cover), its presigned URL is refreshed here and reapplied to
the new playlist; a saved cover_url (an externally-hosted, non-expiring manual link)
is just reused as-is.
"""
from music_embeddings import publish
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

    cover_url = entry.get("cover_url")
    cover_key = entry.get("cover_key")
    if cover_key:
        try:
            client = publish.get_r2_client()
            cover_url = client.generate_presigned_url(
                "get_object", Params={"Bucket": publish.config.R2_BUCKET, "Key": cover_key}, ExpiresIn=86400
            )
        except Exception:
            cover_url = None

    try:
        result_msg = push_playlist_to_plex(
            tracks,
            title,
            overwrite=True,
            plex_url=session["plex_url"],
            plex_token=session["plex_token"],
            cover_url=cover_url,
        )
    except Exception as exc:
        return error_response(f"history-refresh (push) failed: {exc}", status=500, event=event)

    try:
        record_history(
            session["plex_user_id"], title, entry.get("params", {}), meta.get("description"), len(tracks),
            cover_key=cover_key, cover_url=(entry.get("cover_url") if not cover_key else None),
        )
    except Exception:
        pass

    return json_response({"message": result_msg, "track_count": len(tracks)}, event=event)
