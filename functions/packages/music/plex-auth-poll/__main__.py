"""
DO Function: poll a plex.tv PIN, resolve a cloud-reachable server connection, and
(on success) mint a signed session cookie - this is the only place the Plex token
is ever handled directly; every other function only ever sees the session cookie.
"""
from music_embeddings.cloud import json_response, error_response, is_preflight, preflight_response
from music_embeddings.plex_auth import check_pin, get_account_identity, resolve_cloud_plex_connection
from music_embeddings.webauth import mint_session_cookie


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    pin_id = event.get("pin_id")
    if not pin_id:
        return error_response("pin_id is required", status=422, event=event)

    try:
        account_token = check_pin(int(pin_id))
    except Exception as exc:
        return error_response(f"plex-auth/poll failed: {exc}", status=500, event=event)

    if not account_token:
        return json_response({"status": "pending"}, event=event)

    conn_info = resolve_cloud_plex_connection(account_token)
    if conn_info is None:
        return json_response({
            "status": "denied",
            "message": "This Plex account does not have access to the server.",
        }, event=event)

    try:
        identity = get_account_identity(account_token)
    except Exception as exc:
        return error_response(f"Could not fetch Plex account identity: {exc}", status=500, event=event)

    cookie_header = mint_session_cookie(identity, conn_info["token"], conn_info["url"])
    resp = json_response({"status": "ok", "plex_username": identity.get("username")}, event=event)
    resp["headers"]["Set-Cookie"] = cookie_header
    return resp
