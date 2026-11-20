#!/usr/bin/env bash
# Test-only dependencies for scripts/test-services.sh: the production image installs
# torch/torchaudio 2.3.1 from the CUDA 12.1 index (see Dockerfile/constraints.txt).
# Tests run on the CPU, so install the same versions as CPU wheels and constrain to them.
set -euo pipefail
: "${VIRTUAL_ENV:?run via scripts/test-services.sh}"
cd "$(dirname "$0")/.."
uv pip install -q "torch==2.3.1+cpu" "torchaudio==2.3.1+cpu" --index-url https://download.pytorch.org/whl/cpu
sed 's/+cu121/+cpu/' constraints.txt > "$VIRTUAL_ENV/constraints-cpu.txt"
uv pip install -q -r requirements-dev.txt -c "$VIRTUAL_ENV/constraints-cpu.txt" \
  --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match
