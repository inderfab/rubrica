#!/usr/bin/env bash
# Radicale-Entwicklungsserver (CardDAV) fuer Phase 2.
# Aufruf: bash scripts/radicale-dev.sh
set -e

RUBRICA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$HOME/Library/Application Support/Rubrica"
mkdir -p "$DATA_DIR/radicale"

TLS_DIR="$DATA_DIR/radicale-tls"
if [ ! -f "$TLS_DIR/cert.pem" ]; then
  mkdir -p "$TLS_DIR"
  HOSTNAME="$(scutil --get LocalHostName 2>/dev/null || hostname).local"
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$TLS_DIR/key.pem" -out "$TLS_DIR/cert.pem" \
    -days 365 -subj "/CN=$HOSTNAME" \
    -addext "subjectAltName=DNS:$HOSTNAME,DNS:localhost,IP:127.0.0.1" \
    2>&1 | grep -v "^\.*$" || true
  echo "Selbstsigniertes Zertifikat fuer $HOSTNAME generiert ($TLS_DIR)."
fi

HTPASSWD_PATH="$DATA_DIR/radicale-htpasswd"
if [ ! -f "$HTPASSWD_PATH" ]; then
  echo "Kein Radicale-Passwort gesetzt. Bitte zuerst ausfuehren:"
  echo "  .venv/bin/python scripts/radicale_set_password.py fabio <passwort>"
  exit 1
fi

CONFIG_PATH="$DATA_DIR/radicale.conf"
if [ ! -f "$CONFIG_PATH" ]; then
  sed "s|__RUBRICA_DATA_DIR__|$DATA_DIR|g" "$RUBRICA_DIR/config/radicale.conf.example" > "$CONFIG_PATH"
  echo "radicale.conf nach $CONFIG_PATH generiert."
fi

echo "Radicale-Storage: $DATA_DIR/radicale"
echo "CardDAV-Server: https://127.0.0.1:8443 (Benutzer: siehe $HTPASSWD_PATH)"
echo ""

exec "$RUBRICA_DIR/.venv/bin/python3" -m radicale --config "$CONFIG_PATH"
