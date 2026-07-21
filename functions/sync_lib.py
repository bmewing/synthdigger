#!/usr/bin/env python
"""
Copies src/music_embeddings (and plexapi, from the local venv) into functions/lib/
so DO Functions can vendor them via each function's .include file (which references
../../../lib/<name>, flattened to <name> in the deployed package).

plexapi is vendored directly rather than left to the requirements.txt/build.sh path:
it's pure Python (no compiled extensions, just a dependency on requests - already
pre-bundled in DO's runtime), so a straight copy is portable across platforms and
sidesteps DO's requirements.txt/build.sh mechanism entirely for it, which was
observed to silently fail to bundle the installed package into the deployed zip
(cryptography happening to work via that path looks like it's actually pre-present
in the base image, not proof the mechanism itself works).

Run this before `doctl serverless deploy functions/` and before any local testing
that imports the vendored copies. functions/lib/ is gitignored and fully rebuilt
every time, so there is only ever one real copy of each source.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = ROOT / "functions" / "lib"


def _sync(src: Path, dest: Path):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"Synced {src} -> {dest}")


def main():
    _sync(ROOT / "src" / "music_embeddings", LIB_DIR / "music_embeddings")

    try:
        import plexapi
    except ImportError:
        print("WARNING: plexapi not importable in this Python - skipping vendor step "
              "(push/plex-auth-poll/history-refresh need it; pip install plexapi first).",
              file=sys.stderr)
        return
    plexapi_src = Path(plexapi.__file__).resolve().parent
    _sync(plexapi_src, LIB_DIR / "plexapi")


if __name__ == "__main__":
    main()
