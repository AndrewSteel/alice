#!/usr/bin/env bash

exec /opt/venv/bin/wyoming_faster_whisper\
    --uri 'tcp://0.0.0.0:10300' \
    --data-dir /data \
    --download-dir /data "$@"
