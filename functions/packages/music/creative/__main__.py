"""
DO Function: generate a playlist title + matching cover-art prompt via DeepSeek
(routed through OpenRouter).

Fired by the client AFTER `generate` returns the tracklist, so a slow/failed call
here never blocks the tracklist itself from being usable. Uses deepseek-v4-flash
(see generate_creative_assets) rather than v4-pro, whose thinking mode was
observed taking ~22s - close enough to this Function's 28s platform timeout to
occasionally get killed by DO's gateway instead of failing cleanly through our
own error_response.
"""
from music_embeddings.cloud import json_response, error_response, is_preflight, preflight_response
from music_embeddings.playlist import generate_creative_assets
from music_embeddings.webauth import get_session


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    if get_session(event) is None:
        return error_response("Not authenticated - please sign in with Plex.", status=401, event=event)

    description = event.get("description", "")
    tracks = event.get("tracks", [])
    if not tracks:
        return error_response("tracks is required", status=422, event=event)

    try:
        title, cover_prompt = generate_creative_assets(description, tracks)
    except Exception as exc:
        return error_response(f"creative failed: {exc}", status=500, event=event)

    return json_response({"title": title, "cover_prompt": cover_prompt}, event=event)
