#!/usr/bin/env bash
set -euo pipefail

exec /opt/venv/bin/wyoming-faster-whisper\
    --uri 'tcp://0.0.0.0:10300' \
    --data-dir /data \
    --download-dir /data \
    "$@"
