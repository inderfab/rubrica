#!/bin/bash
# Einmalig ausfuehren: bash scripts/setup.sh
set -e

RUBRICA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RUBRICA_DIR"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

mkdir -p logs

# Datenverzeichnis in ~/Library/Application Support/Rubrica
DATA_DIR="$HOME/Library/Application Support/Rubrica"
mkdir -p "$DATA_DIR/logs"
if [ ! -f "$DATA_DIR/config.yaml" ] && [ -f "config.yaml.example" ]; then
  cp config.yaml.example "$DATA_DIR/config.yaml"
  echo "config.yaml nach $DATA_DIR kopiert - bitte anpassen."
fi

echo ""
echo "Setup abgeschlossen. Entwicklungsserver starten mit: bash scripts/dev.sh"
echo "Konfiguration: $DATA_DIR/config.yaml"
echo ""
