#!/bin/bash
# Setzt die Radicale-Auslieferungsschicht komplett zurueck (htpasswd, generiertes
# Passwort, Zugangsdaten-Datei, CardDAV-Collection) und laesst Rubrica sie beim
# naechsten Start sauber neu anlegen. Nuetzlich, wenn config.yaml/htpasswd/
# RADICALE-ZUGANGSDATEN.txt nach manuellen Eingriffen (z.B. altes Migrations-
# Skript, Benutzername-Wechsel) nicht mehr zueinander passen.
#
# rubrica.db (die alleinige Datenquelle, siehe CLAUDE.md) wird NIE angefasst -
# nach dem Reset stellt "Jetzt synchronisieren" in den Einstellungen die
# CardDAV-Collection aus der Datenbank wieder her.
#
# Nichts wird geloescht, nur in einen Zeitstempel-Ordner verschoben.
#
# Aufruf: bash scripts/reset-radicale-clean.sh
set -euo pipefail

DATA_DIR="$HOME/Library/Application Support/Rubrica"
if [ ! -d "$DATA_DIR" ]; then
  echo "Rubrica scheint hier nicht installiert zu sein ($DATA_DIR fehlt)." >&2
  exit 1
fi

UIDN=$(id -u)
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="$DATA_DIR/radicale-reset-backup-$STAMP"
mkdir -p "$BACKUP_DIR"

echo "→ Rubrica-Dienst stoppen…"
launchctl bootout "gui/$UIDN/ch.rubrica.server" 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10; do
  lsof -iTCP:8443 -sTCP:LISTEN >/dev/null 2>&1 || break
  sleep 1
done

echo "→ Alte Dateien nach $BACKUP_DIR verschieben (nichts wird geloescht)…"
for f in "radicale-htpasswd" "RADICALE-ZUGANGSDATEN.txt" "radicale/collection-root"; do
  if [ -e "$DATA_DIR/$f" ]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$f")"
    mv "$DATA_DIR/$f" "$BACKUP_DIR/$f"
    echo "  verschoben: $f"
  fi
done

echo "→ Rubrica-Dienst neu starten (legt Passwort, htpasswd und Zugangsdaten neu + konsistent an)…"
launchctl bootstrap "gui/$UIDN" "$HOME/Library/LaunchAgents/ch.rubrica.server.plist" 2>/dev/null || true

echo "  (warte auf Radicale-Start…)"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  lsof -iTCP:8443 -sTCP:LISTEN >/dev/null 2>&1 && break
  sleep 1
done

echo
echo "=== Fertig ==="
echo "1. Neue Zugangsdaten stehen in:"
echo "   $DATA_DIR/RADICALE-ZUGANGSDATEN.txt"
echo "   (ausserdem als macOS-Dialog beim Neustart erschienen)"
echo "2. Im Browser unter http://localhost:8001/einstellungen auf"
echo "   'Jetzt synchronisieren' klicken - fuellt die leere CardDAV-Collection"
echo "   wieder aus rubrica.db (der alleinigen Datenquelle)."
echo "3. In Kontakte.app das alte CardDAV-Konto entfernen und neu anlegen:"
echo "   Modus 'Manuell' (NICHT 'Erweitert'), nur Hostname (kein Port, kein Pfad),"
echo "   Benutzername 'rubrica', neues Passwort aus Schritt 1."
echo "4. Alte Dateien liegen zur Sicherheit unveraendert in:"
echo "   $BACKUP_DIR"
