"""
DO Function: report the deployed SynthDigger version.

Unauthenticated and side-effect free - the frontend shows it in the footer so an
owner can tell at a glance which build is live (and whether a redeploy is needed).
`schema_version` is the catalog layout this build expects; it's informational here
(the cloud tier reads a published snapshot, it doesn't own the catalog).
"""
from music_embeddings.cloud import json_response, is_preflight, preflight_response
from music_embeddings.version import APP_VERSION, SCHEMA_VERSION


def main(event, context):
    if is_preflight(event):
        return preflight_response(event)

    return json_response({
        "name": "SynthDigger",
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
    }, event=event)
