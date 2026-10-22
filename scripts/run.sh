#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/engine"
if [ "${1:-}" = "--desktop" ]; then
  exec .venv/bin/python desktop/app.py
elif [ $# -gt 0 ]; then
  exec .venv/bin/python -m caa "$@"
else
  exec .venv/bin/python -m caa serve
fi
