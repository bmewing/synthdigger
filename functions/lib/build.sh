#!/bin/bash
set -e
# Runs once before any per-function build, preparing functions/lib/ for every
# function's .include (../../../lib/<name>) to reference. Needed specifically for
# git-based builds (App Platform): functions/lib/music_embeddings and
# functions/lib/plexapi are gitignored build artifacts (see functions/sync_lib.py,
# used for fast local iteration against the standalone Functions namespace), so a
# fresh git checkout never has them - this script is what actually produces them
# in that context, using files already in the repo (src/) plus a pip install for
# the one dependency (plexapi) that isn't.

# music_embeddings: vendor straight from the repo's src/ (this script's cwd is
# functions/lib/, so the repo root is two levels up).
rm -rf music_embeddings
cp -r ../../src/music_embeddings ./music_embeddings
find ./music_embeddings -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# plexapi: pure Python, no compiled extensions, so installing it directly (rather
# than requirements.txt + per-function build.sh, which was observed to silently
# fail to bundle it) is reliable across platforms. This lib-build stage's
# environment has neither pip/python NOR unzip (confirmed empirically - it's a
# minimal shell, not a language-specific container), so the fallback fetches the
# sdist (.tar.gz, not the .whl) straight from PyPI: tar is far more likely than
# unzip to exist in a bare-bones shell, and only curl/tar are needed for this path.
rm -rf plexapi
PLEXAPI_VERSION=4.18.2
if command -v pip >/dev/null 2>&1; then
  pip install --target . --no-deps "plexapi==${PLEXAPI_VERSION}"
elif command -v pip3 >/dev/null 2>&1; then
  pip3 install --target . --no-deps "plexapi==${PLEXAPI_VERSION}"
elif command -v python3 >/dev/null 2>&1; then
  python3 -m pip install --target . --no-deps "plexapi==${PLEXAPI_VERSION}"
elif command -v python >/dev/null 2>&1; then
  python -m pip install --target . --no-deps "plexapi==${PLEXAPI_VERSION}"
else
  echo "No pip/python found - fetching the plexapi sdist directly from PyPI" >&2
  META_URL="https://pypi.org/pypi/plexapi/${PLEXAPI_VERSION}/json"
  SDIST_URL=$(curl -sL "$META_URL" | grep -o '"url":"[^"]*\.tar\.gz"' | head -1 | sed -E 's/"url":"([^"]*)"/\1/')
  curl -sL "$SDIST_URL" -o /tmp/plexapi.tar.gz
  rm -rf /tmp/plexapi_extracted
  mkdir -p /tmp/plexapi_extracted
  tar xzf /tmp/plexapi.tar.gz -C /tmp/plexapi_extracted
  cp -r "/tmp/plexapi_extracted/plexapi-${PLEXAPI_VERSION}/plexapi" ./plexapi
fi
