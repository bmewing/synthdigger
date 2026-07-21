# Daily job: pull latest play counts/ratings from Plex into the local catalog,
# then re-publish the embeddings/tracks/labels snapshot to R2 so the cloud app
# reflects current listening activity.
#
# Windows Task Scheduler example. On Linux/macOS, cron the same two commands:
#   python -m music_embeddings.cli sync-plex && python -m music_embeddings.cli publish
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
# Task Scheduler launches with an arbitrary CWD (often System32); relative
# paths in the pipeline (e.g. .env discovery) must resolve against the repo.
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
$log = Join-Path $root "logs\refresh_plex_r2.log"

New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

"[$(Get-Date -Format s)] Starting Plex -> R2 refresh" | Out-File -Append -Encoding utf8 $log

try {
    & $python -m music_embeddings.cli sync-plex 2>&1 | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) { throw "sync-plex exited with code $LASTEXITCODE" }

    & $python -m music_embeddings.cli publish 2>&1 | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) { throw "publish exited with code $LASTEXITCODE" }

    "[$(Get-Date -Format s)] Refresh completed successfully" | Out-File -Append -Encoding utf8 $log
} catch {
    "[$(Get-Date -Format s)] Refresh FAILED: $_" | Out-File -Append -Encoding utf8 $log
    exit 1
}
