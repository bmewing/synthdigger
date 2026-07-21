"""
Plex authentication helpers.

Two capabilities:
1. PIN-based sign-in (the official plex.tv "link" flow): create a PIN, send the
   user to app.plex.tv to sign in, then poll until plex.tv hands back a token.
2. Token resolution: Home/shared users' plex.tv account tokens are NOT accepted
   directly by a Plex Media Server - each shared user gets a server-scoped
   access token via the plex.tv resources API. resolve_working_token() takes
   any candidate token and returns one that actually works against PLEX_URL.
"""
import logging
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

from music_embeddings import config

logger = logging.getLogger("music_embeddings.plex_auth")

CLIENT_ID = "music-discovery-webapp"
PRODUCT = "Music Discovery"

_HEADERS = {
    "Accept": "application/json",
    "X-Plex-Product": PRODUCT,
    "X-Plex-Client-Identifier": CLIENT_ID,
}

_server_machine_id: Optional[str] = None


def create_pin() -> Dict[str, Any]:
    """Creates a plex.tv PIN. Returns {'id': ..., 'code': ...}."""
    r = requests.post(
        "https://plex.tv/api/v2/pins", params={"strong": "true"}, headers=_HEADERS, timeout=10
    )
    r.raise_for_status()
    d = r.json()
    return {"id": d["id"], "code": d["code"]}


def auth_url(code: str) -> str:
    """The app.plex.tv URL where the user signs in to authorize the PIN."""
    return (
        "https://app.plex.tv/auth#?clientID=" + quote(CLIENT_ID)
        + "&code=" + quote(code)
        + "&context%5Bdevice%5D%5Bproduct%5D=" + quote(PRODUCT)
    )


def check_pin(pin_id: int) -> Optional[str]:
    """Returns the account auth token once the user has signed in, else None."""
    r = requests.get(f"https://plex.tv/api/v2/pins/{pin_id}", headers=_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json().get("authToken") or None


def get_account_identity(account_token: str) -> Dict[str, Any]:
    """
    Fetches the signed-in plex.tv account's identity, used to key the cloud app's
    session (not the server-scoped token, which is per-server rather than per-person).
    Returns {"id": int, "username": str, "email": str, "title": str}.
    """
    r = requests.get(
        "https://plex.tv/api/v2/user",
        headers={**_HEADERS, "X-Plex-Token": account_token},
        timeout=10,
    )
    r.raise_for_status()
    d = r.json()
    return {
        "id": d.get("id"),
        "username": d.get("username"),
        "email": d.get("email"),
        "title": d.get("title") or d.get("friendlyName"),
    }


def _get_server_machine_id() -> Optional[str]:
    """The machineIdentifier of our Plex server (cached after first lookup)."""
    global _server_machine_id
    if _server_machine_id is None:
        try:
            from plexapi.server import PlexServer

            _server_machine_id = PlexServer(config.PLEX_URL, config.PLEX_TOKEN).machineIdentifier
        except Exception as exc:
            logger.warning("Could not determine server machineIdentifier: %s", exc)
    return _server_machine_id


def _token_works(token: str) -> bool:
    try:
        from plexapi.server import PlexServer

        PlexServer(config.PLEX_URL, token)
        return True
    except Exception:
        return False


def resolve_working_token(candidate: str) -> Optional[str]:
    """
    Returns a token accepted by the Plex server at PLEX_URL, or None.

    Tries the candidate directly first (works for the server owner). If the
    server rejects it, exchanges it via plex.tv for the user's server-scoped
    access token (required for Home/shared users).
    """
    candidate = (candidate or "").strip()
    if not candidate:
        return None

    if _token_works(candidate):
        return candidate

    logger.info("Token rejected by server directly; trying plex.tv resource exchange...")
    try:
        r = requests.get(
            "https://plex.tv/api/v2/resources",
            params={"includeHttps": "1", "includeRelay": "0"},
            headers={**_HEADERS, "X-Plex-Token": candidate},
            timeout=10,
        )
        r.raise_for_status()
        resources = r.json()
    except Exception as exc:
        logger.warning("plex.tv resources lookup failed: %s", exc)
        return None

    servers = [
        res for res in resources
        if "server" in (res.get("provides") or "") and res.get("accessToken")
    ]
    # Prefer the resource matching our server's machineIdentifier
    machine_id = _get_server_machine_id()
    servers.sort(key=lambda res: res.get("clientIdentifier") != machine_id)

    for res in servers:
        token = res["accessToken"]
        if _token_works(token):
            logger.info("Resolved server-scoped token via resource '%s'", res.get("name"))
            return token

    return None


def resolve_cloud_plex_connection(candidate_token: str, timeout: float = 6.0) -> Optional[Dict[str, str]]:
    """
    Cloud-safe variant of resolve_working_token(): never touches the local-network
    PLEX_URL (unreachable from a cloud Function - trying it could hang rather than
    fail fast). Instead, looks up the account's plex.tv resources, filters to the
    server matching config.PLEX_SERVER_MACHINE_ID, and tries each of that server's
    non-local, non-relay connections (its public plex.direct URL, reachable when Plex
    Remote Access is enabled) with the candidate token or the resource's own
    server-scoped token.

    Returns {"url": ..., "token": ...} for the first connection that works, else None.
    """
    candidate = (candidate_token or "").strip()
    if not candidate:
        return None

    try:
        r = requests.get(
            "https://plex.tv/api/v2/resources",
            params={"includeHttps": "1", "includeRelay": "0"},
            headers={**_HEADERS, "X-Plex-Token": candidate},
            timeout=10,
        )
        r.raise_for_status()
        resources = r.json()
    except Exception as exc:
        logger.warning("plex.tv resources lookup failed: %s", exc)
        return None

    servers = [
        res for res in resources
        if "server" in (res.get("provides") or "") and res.get("accessToken")
    ]
    if config.PLEX_SERVER_MACHINE_ID:
        matched = [res for res in servers if res.get("clientIdentifier") == config.PLEX_SERVER_MACHINE_ID]
        if matched:
            servers = matched
        else:
            logger.warning(
                "No plex.tv resource matched PLEX_SERVER_MACHINE_ID=%s for this account.",
                config.PLEX_SERVER_MACHINE_ID,
            )
            return None

    from plexapi.server import PlexServer

    for res in servers:
        candidate_tokens = [candidate, res["accessToken"]]
        remote_conns = [c for c in res.get("connections", []) if not c.get("local") and not c.get("relay")]
        for conn in remote_conns:
            url = conn.get("uri")
            if not url:
                continue
            for tok in candidate_tokens:
                try:
                    PlexServer(url, tok, timeout=timeout)
                    logger.info("Resolved cloud-reachable Plex connection '%s' via resource '%s'", url, res.get("name"))
                    return {"url": url, "token": tok}
                except Exception:
                    continue

    return None
