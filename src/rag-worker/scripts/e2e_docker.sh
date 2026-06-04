#!/usr/bin/env bash
# Run the rag-worker e2e suite in Docker (Linux) against a REAL AI provider.
#
# Why Docker: native deps (PyMuPDF `_extra`, onnxruntime via markitdown->magika)
# need the MSVC runtime on Windows and fail with "DLL load failed". The Linux
# image sidesteps that. See docs/ops/native-deps.md.
#
# Usage (from anywhere):
#   scripts/e2e_docker.sh                         # build + run full tests/e2e
#   scripts/e2e_docker.sh tests/e2e/test_validation_ocr_corpus.py   # one target
#   SKIP_BUILD=1 scripts/e2e_docker.sh            # reuse existing image
#   ENV_FILE=/path/to/.env scripts/e2e_docker.sh  # override secrets file
#   IMAGE=rag-worker:dev scripts/e2e_docker.sh    # override image tag
#
# The provider/keys come from ENV_FILE (default: repo-root .env), passed via
# --env-file. RAG_EVAL_REAL_PROVIDER=1 makes the validation + OCR corpus tests
# hit the real gateway instead of the offline stub.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"        # src/rag-worker
REPO_ROOT="$(cd "$WORKER_DIR/../.." && pwd)"      # repo root

IMAGE="${IMAGE:-rag-worker:eval}"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
TARGET="${*:-tests/e2e}"                          # pytest target(s); default full e2e

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: env file not found: $ENV_FILE (override with ENV_FILE=...)" >&2
  exit 1
fi
# cd into the env file's dir and pass a relative name: docker.exe on Windows does
# not understand git-bash absolute paths like /d/... but resolves relative ones.
ENV_DIR="$(cd "$(dirname "$ENV_FILE")" && pwd)"
ENV_BASE="$(basename "$ENV_FILE")"

if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo ">> build $IMAGE  (context: $WORKER_DIR)"
  ( cd "$WORKER_DIR" && docker build -t "$IMAGE" . )
fi

echo ">> e2e (real provider) :: $TARGET"
( cd "$ENV_DIR" && docker run --rm \
    --env-file "$ENV_BASE" \
    -e RAG_EVAL_REAL_PROVIDER=1 \
    -e APP_ENV=development \
    "$IMAGE" \
    python -m pytest $TARGET -q -ra )
