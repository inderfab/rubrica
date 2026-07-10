#!/usr/bin/env bash
# Entwicklungsserver. Aufruf: bash scripts/dev.sh
set -e

RUBRICA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export RUBRICA_DATA_DIR="$HOME/Library/Application Support/Rubrica"

cd "$RUBRICA_DIR"

echo "Config + DB: $RUBRICA_DATA_DIR"
echo "Server: http://localhost:8000"
echo ""

exec .venv/bin/uvicorn web.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --reload \
  --log-level info
