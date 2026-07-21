"""
Session handling for the cloud app: signs in via Plex, then gates every other
Function behind a session cookie so only people with access to the target Plex
server can use it at all (not just push to it).

The session is a signed token (HMAC-SHA256 over a base64 JSON payload, in the
same style as Flask/Django's session cookies) carrying the signed-in Plex
identity plus the already-resolved server-scoped Plex token and its
cloud-reachable URL. Embedding the resolved connection (rather than just the
raw account token) means `push` and friends never have to re-run the plex.tv
resource-discovery round trip per request.

This is signing, not encryption: the payload (including the user's own Plex
token) is base64-visible to anyone who reads the raw cookie value, but the
cookie is HttpOnly (client-side JS never sees it) and only travels over HTTPS
(Secure). The token in it already belongs to whoever is signed in, so hiding
it from them isn't a real security boundary - what matters is that it can't be
forged or tampered with, which HMAC verification (via hmac.compare_digest, so
timing-safe) guarantees. Using stdlib hmac/hashlib instead of the
`cryptography` package sidesteps that package's compiled-extension build
entirely, which DO Functions' remote build step could not reliably produce.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from music_embeddings import config

logger = logging.getLogger("music_embeddings.webauth")

SESSION_COOKIE_NAME = "music_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _secret_key() -> bytes:
    if not config.SESSION_SECRET_KEY:
        raise ValueError("SESSION_SECRET_KEY is not configured.")
    return config.SESSION_SECRET_KEY.encode("utf-8")


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload_b64: str) -> str:
    mac = hmac.new(_secret_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64e(mac)


def _secure_attr() -> str:
    """
    "; Secure" in production (required - the cookie must never be sent over plain
    HTTP), omitted only when SESSION_COOKIE_INSECURE is set for local dev testing
    against the plain-http local_dev_server.py: real browsers silently refuse to
    store a Secure cookie set over http://localhost, which would make local login
    look like it worked (200 + Set-Cookie) while silently never persisting.
    """
    return "" if os.environ.get("SESSION_COOKIE_INSECURE") else "; Secure"


def mint_session_cookie(plex_identity: Dict[str, Any], plex_token: str, plex_url: str) -> str:
    """
    Signs the session payload and returns a full Set-Cookie header value ready
    to attach to a Function's response headers.
    """
    payload = {
        "plex_user_id": plex_identity.get("id"),
        "plex_username": plex_identity.get("username"),
        "plex_title": plex_identity.get("title"),
        "plex_token": plex_token,
        "plex_url": plex_url,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    payload_b64 = _b64e(json.dumps(payload).encode("utf-8"))
    token = f"{payload_b64}.{_sign(payload_b64)}"
    return (
        f"{SESSION_COOKIE_NAME}={token}; HttpOnly{_secure_attr()}; SameSite=Lax; "
        f"Max-Age={SESSION_TTL_SECONDS}; Path=/"
    )


def clear_session_cookie() -> str:
    """Set-Cookie value that expires the session immediately (for a logout action)."""
    return f"{SESSION_COOKIE_NAME}=; HttpOnly{_secure_attr()}; SameSite=Lax; Max-Age=0; Path=/"


def _parse_cookie_header(cookie_header: str) -> Dict[str, str]:
    cookies = {}
    for part in cookie_header.split(";"):
        if "=" in part:
            key, _, value = part.strip().partition("=")
            cookies[key] = value
    return cookies


def get_session(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validates and decodes the session cookie from a DO Function event. Returns the
    decoded session dict, or None if the cookie is missing, invalid, tampered with,
    or expired.
    """
    http = event.get("http", {}) if isinstance(event, dict) else {}
    headers = http.get("headers", {}) or {}
    cookie_header = headers.get("cookie", "") or headers.get("Cookie", "")
    if not cookie_header:
        return None

    token = _parse_cookie_header(cookie_header).get(SESSION_COOKIE_NAME)
    if not token:
        return None

    payload_b64, sep, sig = token.partition(".")
    if not sep or not sig:
        return None

    try:
        expected_sig = _sign(payload_b64)
    except Exception as exc:
        logger.info("Session cookie rejected: %s", exc)
        return None

    if not hmac.compare_digest(expected_sig, sig):
        logger.info("Session cookie rejected: signature mismatch")
        return None

    try:
        payload = json.loads(_b64d(payload_b64).decode("utf-8"))
    except Exception as exc:
        logger.info("Session cookie rejected: %s", exc)
        return None

    if payload.get("exp", 0) < time.time():
        logger.info("Session cookie rejected: expired")
        return None

    return payload
