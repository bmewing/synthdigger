# Monthly job: re-score every embedded track with the deployed style/mood
# taggers (catches drift and any tracks the incremental per-file path missed),
# then re-publish the embeddings/tracks/labels snapshot to R2.
#
# Windows Task Scheduler example. On Linux/macOS, cron the same three commands:
#   python -m music_embeddings.cli predict-tags style --to-db && \
#   python -m music_embeddings.cli predict-tags mood --to-db && \
#   python -m music_embeddings.cli publish
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
# Task Scheduler launches with an arbitrary CWD (often System32); relative
# paths in the pipeline (e.g. .env discovery) must resolve against the repo.
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
$log = Join-Path $root "logs\refresh_style_mood_r2.log"

New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

"[$(Get-Date -Format s)] Starting monthly style/mood rescore" | Out-File -Append -Encoding utf8 $log

try {
    & $python -m music_embeddings.cli predict-tags style --to-db 2>&1 | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) { throw "predict-tags style exited with code $LASTEXITCODE" }

    & $python -m music_embeddings.cli predict-tags mood --to-db 2>&1 | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) { throw "predict-tags mood exited with code $LASTEXITCODE" }

    & $python -m music_embeddings.cli publish 2>&1 | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) { throw "publish exited with code $LASTEXITCODE" }

    "[$(Get-Date -Format s)] Monthly rescore completed successfully" | Out-File -Append -Encoding utf8 $log
} catch {
    "[$(Get-Date -Format s)] Monthly rescore FAILED: $_" | Out-File -Append -Encoding utf8 $log
    exit 1
}
