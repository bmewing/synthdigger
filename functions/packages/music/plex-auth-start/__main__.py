"""DO Function: create a plex.tv PIN and return the sign-in URL."""
from music_embeddings.cloud import json_response, error_response, is_preflight, preflight_response
from music_embeddings.plex_auth import create_pin, auth_url


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    try:
        pin = create_pin()
    except Exception as exc:
        return error_response(f"plex-auth/start failed: {exc}", status=500, event=event)

    return json_response({"pin_id": pin["id"], "auth_url": auth_url(pin["code"])}, event=event)
