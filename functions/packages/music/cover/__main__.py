"""
DO Function: generate AI cover art via OpenRouter.

Fired by the client after `creative` returns its prompt (or with description/tracks
alone, falling back to the generic template) - independent of `generate` so a slow
image call never blocks the tracklist.

The image is uploaded to R2 and a presigned URL is returned rather than inlining the
PNG as base64: DO Functions' web-action response has a size cap well under what a
full generated image encodes to, and exceeding it previously failed as an opaque
platform-level error ("Response is not valid 'message/http'") instead of anything
our own error handling could catch. `push` already knows how to hand a cover URL to
Plex, so this is a drop-in swap for the client.
"""
import uuid

from music_embeddings import publish
from music_embeddings.cloud import json_response, error_response, is_preflight, preflight_response
from music_embeddings.playlist import generate_ai_cover_image
from music_embeddings.webauth import get_session


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    session = get_session(event)
    if session is None:
        return error_response("Not authenticated - please sign in with Plex.", status=401, event=event)

    description = event.get("description", "")
    tracks = event.get("tracks", [])
    prompt = event.get("prompt")

    try:
        image_bytes = generate_ai_cover_image(description, tracks, prompt=prompt)
    except Exception as exc:
        return error_response(f"cover failed: {exc}", status=500, event=event)

    if image_bytes is None:
        return json_response({"cover_url": None}, event=event)

    try:
        client = publish.get_r2_client()
        key = f"covers/{session['plex_user_id']}/{uuid.uuid4().hex}.png"
        client.put_object(Bucket=publish.config.R2_BUCKET, Key=key, Body=image_bytes, ContentType="image/png")
        cover_url = client.generate_presigned_url(
            "get_object", Params={"Bucket": publish.config.R2_BUCKET, "Key": key}, ExpiresIn=86400
        )
    except Exception as exc:
        return error_response(f"cover generated but failed to store it: {exc}", status=500, event=event)

    return json_response({"cover_url": cover_url, "cover_key": key}, event=event)
