#!/bin/bash
# Migriert eine bestehende Installation vom alten, macOS-Benutzername-abhaengigen
# Radicale-Konto auf den neuen, fest verdrahteten Namen "rubrica" (siehe
# sync/radicale.py RADICALE_BENUTZER). Idempotent - mehrfaches Ausfuehren ist
# unproblematisch.
#
# Aufruf: bash scripts/migrate-radicale-user.sh
set -euo pipefail

DATA_DIR="$HOME/Library/Application Support/Rubrica"
if [ ! -d "$DATA_DIR" ]; then
  echo "Rubrica scheint hier nicht installiert zu sein ($DATA_DIR fehlt)." >&2
  exit 1
fi

UIDN=$(id -u)
NEUER_BENUTZER="rubrica"
COLLECTION_ROOT="$DATA_DIR/radicale/collection-root"

# Python-Interpreter ermitteln: bevorzugt eingebettetes Python aus dem gepackten
# .app-Bundle (Contents/Resources, seit der Signierungs-Umstellung - Contents/
# Frameworks als Fallback fuer Builds vor dieser Umstellung), sonst Dev-Venv.
ARCH=$(uname -m)
APP_RESOURCES="/Applications/Rubrica Server.app/Contents/Resources"
APP_FRAMEWORKS="/Applications/Rubrica Server.app/Contents/Frameworks"
if [ -x "$APP_RESOURCES/rubrica-python-$ARCH/bin/python3" ]; then
  RUBRICA_PYTHON="$APP_RESOURCES/rubrica-python-$ARCH/bin/python3"
  SCRIPT_DIR="$APP_RESOURCES"
elif [ -x "$APP_FRAMEWORKS/rubrica-python-$ARCH/bin/python3" ]; then
  RUBRICA_PYTHON="$APP_FRAMEWORKS/rubrica-python-$ARCH/bin/python3"
  SCRIPT_DIR="$APP_RESOURCES"
else
  RUBRICA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
  RUBRICA_PYTHON="$RUBRICA_DIR/.venv/bin/python3"
  SCRIPT_DIR="$RUBRICA_DIR/scripts"
fi
if [ ! -x "$RUBRICA_PYTHON" ]; then
  echo "Kein Python-Interpreter gefunden (weder eingebettet noch .venv)." >&2
  exit 1
fi

echo "→ Rubrica-Dienste stoppen…"
launchctl bootout "gui/$UIDN/ch.rubrica.server" 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10; do
  lsof -iTCP:8443 -sTCP:LISTEN >/dev/null 2>&1 || break
  sleep 1
done

ALTER_BENUTZER=$(ls "$COLLECTION_ROOT" 2>/dev/null | grep -v "^$NEUER_BENUTZER\$" | head -1 || true)

if [ -n "$ALTER_BENUTZER" ] && [ ! -d "$COLLECTION_ROOT/$NEUER_BENUTZER" ]; then
  echo "→ Collection-Ordner umbenennen: '$ALTER_BENUTZER' -> '$NEUER_BENUTZER'…"
  mv "$COLLECTION_ROOT/$ALTER_BENUTZER" "$COLLECTION_ROOT/$NEUER_BENUTZER"
elif [ -d "$COLLECTION_ROOT/$NEUER_BENUTZER" ]; then
  echo "→ Collection-Ordner '$NEUER_BENUTZER' existiert bereits - nichts umzubenennen."
else
  echo "→ Kein bestehender Collection-Ordner gefunden - lege '$NEUER_BENUTZER' neu an."
  mkdir -p "$COLLECTION_ROOT/$NEUER_BENUTZER"
fi

COLL="$COLLECTION_ROOT/$NEUER_BENUTZER/kontakte"
mkdir -p "$COLL"

# Radicale erkennt ein Verzeichnis nur dann als CardDAV-Adressbuch (statt als
# generische WebDAV-Collection), wenn .Radicale.props den Tag VADDRESSBOOK
# enthaelt (siehe scripts/restore-data-archive.sh fuer die volle Erklaerung des
# Symptoms ohne diese Datei: Verbindung klappt, Kontakte bleiben leer).
if [ ! -f "$COLL/.Radicale.props" ]; then
  printf '{"D:displayname": "Rubrica", "tag": "VADDRESSBOOK"}' > "$COLL/.Radicale.props"
  echo "→ .Radicale.props angelegt (fehlte - Adressbuch-Kennzeichnung nachgetragen)"
fi

echo "→ htpasswd-Eintrag migrieren…"
if [ -n "$ALTER_BENUTZER" ]; then
  "$RUBRICA_PYTHON" "$SCRIPT_DIR/radicale_migrate_user.py" "$ALTER_BENUTZER" "$NEUER_BENUTZER"
else
  "$RUBRICA_PYTHON" "$SCRIPT_DIR/radicale_migrate_user.py" "$NEUER_BENUTZER" "$NEUER_BENUTZER"
fi

echo "→ Radicale-Cache zuruecksetzen und einmal aufwaermen…"
rm -rf "$COLL/.Radicale.cache"

echo "→ Rubrica-Dienste neu starten…"
launchctl bootstrap "gui/$UIDN" "$HOME/Library/LaunchAgents/ch.rubrica.server.plist" 2>/dev/null || true

echo "  (warte auf Radicale-Start…)"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  lsof -iTCP:8443 -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 1
done

# Kaltstart-Aufwaermen: bei sehr grossen Adressbuechern (>1000 Karten) kann der
# erste PROPFIND mehrere Minuten dauern - macOS' Sync-Client gibt vorher auf.
# Einmal synchron hier ausloesen, statt das erste Kontakte.app-Login damit zu
# belasten.
echo "→ Adressbuch einmal aufwaermen (kann bei vielen Kontakten dauern)…"
curl -k -s -o /dev/null -X PROPFIND "https://127.0.0.1:8443/$NEUER_BENUTZER/kontakte/" \
  -H "Depth: 1" --max-time 180 || echo "  (Aufwaermen fehlgeschlagen oder Timeout - beim ersten echten Zugriff wird nachgeholt)"

echo
echo "=== Fertig ==="
echo "Das CardDAV-Konto in Kontakte.app muss neu angelegt werden (ein bestehendes"
echo "Konto laesst sich nicht zuverlaessig umbenennen):"
echo "  1. Altes Konto (falls vorhanden) in Kontakte.app entfernen."
echo "  2. Neues Konto anlegen, Modus 'Manuell' waehlen (NICHT 'Erweitert')."
echo "  3. Nur den Hostnamen eintragen (ohne Port, ohne Pfad)."
echo "  4. Benutzername: $NEUER_BENUTZER"
echo "  5. Passwort: unveraendert (siehe config.yaml radicale.password)."
