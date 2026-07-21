"""
Cloud-writable playlist history: one JSON file per Plex account in R2
(`history/{plex_user_id}.json`), since a Function pushing a playlist can't write to
the local database that the offline pipeline maintains.

Upserts by title (re-pushing the same title updates its saved entry rather than
duplicating it), keyed by the authenticated Plex account id.

No locking/versioning: one small JSON file per account, read-modify-write, is only
ever touched by that one account's own requests - not worth a compare-and-swap
scheme R2 doesn't cleanly offer anyway.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from music_embeddings import publish

logger = logging.getLogger("music_embeddings.cloud_history")


def _history_key(plex_user_id: Any) -> str:
    return f"history/{plex_user_id}.json"


def load_history(plex_user_id: Any) -> List[Dict[str, Any]]:
    """Returns the saved entries for this account, newest-updated first, or [] if none yet."""
    client = publish.get_r2_client()
    try:
        obj = client.get_object(Bucket=publish.config.R2_BUCKET, Key=_history_key(plex_user_id))
        return json.loads(obj["Body"].read().decode("utf-8"))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            return []
        raise


def save_history(plex_user_id: Any, entries: List[Dict[str, Any]]) -> None:
    client = publish.get_r2_client()
    client.put_object(
        Bucket=publish.config.R2_BUCKET,
        Key=_history_key(plex_user_id),
        Body=json.dumps(entries).encode("utf-8"),
        ContentType="application/json",
    )


def record_history(
    plex_user_id: Any,
    title: str,
    params: Dict[str, Any],
    description: Optional[str],
    track_count: int,
    cover_key: Optional[str] = None,
    cover_url: Optional[str] = None,
) -> None:
    """
    Insert a new entry, or update it in place if an entry with this title already exists.

    `cover_key` is the R2 object key for an AI-generated cover (its presigned URL expires,
    but the object itself is kept forever, so history-refresh can re-presign it later).
    `cover_url` is a stable externally-hosted cover (manually pasted, not ours to re-presign).
    Neither is required on every call - passing neither leaves whatever a prior push already
    saved untouched, so refreshing a playlist that has no new cover doesn't drop the old one.
    """
    entries = load_history(plex_user_id)
    now = datetime.now(timezone.utc).isoformat()

    for entry in entries:
        if entry.get("title") == title:
            entry.update(params=params, description=description, track_count=track_count, updated_at=now)
            if cover_key is not None:
                entry["cover_key"] = cover_key
                entry.pop("cover_url", None)
            elif cover_url is not None:
                entry["cover_url"] = cover_url
                entry.pop("cover_key", None)
            break
    else:
        entries.append({
            "title": title,
            "params": params,
            "description": description,
            "track_count": track_count,
            "cover_key": cover_key,
            "cover_url": cover_url,
            "created_at": now,
            "updated_at": now,
        })

    entries.sort(key=lambda e: e["updated_at"], reverse=True)
    save_history(plex_user_id, entries)


def get_history_entry(plex_user_id: Any, title: str) -> Optional[Dict[str, Any]]:
    for entry in load_history(plex_user_id):
        if entry.get("title") == title:
            return entry
    return None


def delete_history_entry(plex_user_id: Any, title: str) -> bool:
    """Returns True if an entry was found and removed."""
    entries = load_history(plex_user_id)
    remaining = [e for e in entries if e.get("title") != title]
    if len(remaining) == len(entries):
        return False
    save_history(plex_user_id, remaining)
    return True
