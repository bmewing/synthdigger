"""DO Function: seed-song autocomplete against the published parquet data."""
from music_embeddings.cloud import get_cached_datasource, json_response, error_response, is_preflight, preflight_response
from music_embeddings.webauth import get_session


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    if get_session(event) is None:
        return error_response("Not authenticated - please sign in with Plex.", status=401, event=event)

    query = (event.get("q") or event.get("query") or "").strip()
    if not query:
        return json_response({"matches": []}, event=event)

    try:
        datasource = get_cached_datasource()
        matches = datasource.resolve_seed_songs(query)
    except Exception as exc:
        return error_response(f"seed-search failed: {exc}", status=500, event=event)

    slim = [
        {
            "sha256": m["sha256"],
            "rating_key": m["rating_key"],
            "artist": m["artist"],
            "title": m["title"],
            "album": m["album"],
        }
        for m in matches
    ]
    return json_response({"matches": slim}, event=event)
