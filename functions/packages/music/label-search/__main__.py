"""DO Function: mood/style/genre autocomplete against the published parquet data."""
from music_embeddings.cloud import get_cached_datasource, json_response, error_response, is_preflight, preflight_response
from music_embeddings.webauth import get_session

_FIELD_TO_SOURCE = {
    "genre": "discogs genre",
    "style": "allmusic style",
    "mood": "allmusic mood",
}


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    if get_session(event) is None:
        return error_response("Not authenticated - please sign in with Plex.", status=401, event=event)

    field = event.get("field")
    query = (event.get("q") or event.get("query") or "").strip()
    source = _FIELD_TO_SOURCE.get(field)

    try:
        datasource = get_cached_datasource()
        labels = datasource.list_available_labels(source=source, filter_query=query, limit=10)
    except Exception as exc:
        return error_response(f"label-search failed: {exc}", status=500, event=event)

    return json_response({"labels": labels}, event=event)
