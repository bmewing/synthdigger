"""DO Function: clear the session cookie."""
from music_embeddings.cloud import json_response, is_preflight, preflight_response
from music_embeddings.webauth import clear_session_cookie


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    resp = json_response({"status": "ok"}, event=event)
    resp["headers"]["Set-Cookie"] = clear_session_cookie()
    return resp
