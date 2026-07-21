"""
DO Function: bulk data for the frontend's seed-song/genre/style/mood typeahead
fields, fetched once on page load and filtered client-side afterward instead of
calling seed-search/label-search on every keystroke (those load the full
embeddings matrix via get_cached_datasource, which is slow on a cold container).
"""
from music_embeddings import config
from music_embeddings.cloud import get_cached_autocomplete_data, json_response, error_response, is_preflight, preflight_response
from music_embeddings.webauth import get_session


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    if get_session(event) is None:
        return error_response("Not authenticated - please sign in with Plex.", status=401, event=event)

    try:
        data = get_cached_autocomplete_data()
    except Exception as exc:
        return error_response(f"autocomplete-data failed: {exc}", status=500, event=event)

    # Lets the frontend hide the vibe input + AI title/cover buttons when AI is
    # disabled or unconfigured, without a dedicated endpoint or round-trip.
    ai_enabled = bool(config.OPENROUTER_API_KEY) and not config.DISABLE_AI_FEATURES
    return json_response({**data, "ai_enabled": ai_enabled}, event=event)
