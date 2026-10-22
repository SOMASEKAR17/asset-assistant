#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
"$PY" -c "import sys; assert sys.version_info >= (3, 10), sys.version"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r engine/requirements.txt
if [ "${1:-}" != "--no-models" ]; then
  .venv/bin/python -m pip install -r engine/requirements-ml.txt
fi
command -v ffmpeg >/dev/null || echo "FFmpeg missing: brew install ffmpeg  /  sudo apt install ffmpeg"
[ -f .env ] || cp .env.example .env
PYTHONPATH="$ROOT/engine" .venv/bin/python -m caa doctor
echo "Start with: scripts/run.sh"
