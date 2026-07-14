#!/bin/bash
# Spielt ein Rubrica-Datenarchiv (rubrica.db + kontakte-vcf/) auf DIESER Maschine
# ein - z.B. um Kontakte/Ordner von einer Test-Instanz (Mac Studio) auf die
# Produktions-Instanz (iMac) zu uebertragen. Ersetzt NICHT Zertifikat/Passwort/
# Config - die bleiben pro Maschine eigenstaendig (siehe docs/konzept.md Abschnitt 9).
#
# Aufruf: bash scripts/restore-data-archive.sh /Pfad/zu/rubrica-migration-daten.tar.gz
set -euo pipefail

ARCHIVE="${1:?Pfad zum Archiv fehlt. Aufruf: bash restore-data-archive.sh /Pfad/zu/rubrica-migration-daten.tar.gz}"
if [ ! -f "$ARCHIVE" ]; then
  echo "Archiv nicht gefunden: $ARCHIVE" >&2
  exit 1
fi

DATA_DIR="$HOME/Library/Application Support/Rubrica"
if [ ! -d "$DATA_DIR" ]; then
  echo "Rubrica scheint hier nicht installiert zu sein ($DATA_DIR fehlt)." >&2
  exit 1
fi

UIDN=$(id -u)
LA_DIR="$HOME/Library/LaunchAgents"

echo "→ Rubrica-Dienste stoppen…"
launchctl bootout "gui/$UIDN/ch.strut.rubrica.server" 2>/dev/null || true
launchctl bootout "gui/$UIDN/ch.strut.rubrica.radicale" 2>/dev/null || true
sleep 1

echo "→ Aktuellen Stand sichern (falls vorhanden)…"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$DATA_DIR/vor-restore-backup-$STAMP"
mkdir -p "$BACKUP"
[ -f "$DATA_DIR/rubrica.db" ] && cp "$DATA_DIR/rubrica.db" "$BACKUP/"
[ -d "$DATA_DIR/radicale/collection-root" ] && cp -r "$DATA_DIR/radicale/collection-root" "$BACKUP/"
echo "  Backup unter: $BACKUP"

echo "→ Archiv entpacken…"
WORK=$(mktemp -d)
tar xzf "$ARCHIVE" -C "$WORK"

echo "→ Datenbank einspielen…"
cp "$WORK/rubrica.db" "$DATA_DIR/rubrica.db"

echo "→ Radicale-CardDAV-Benutzernamen dieser Maschine ermitteln…"
# Fest verdrahtet auf "pas" (siehe sync/radicale.py RADICALE_BENUTZER) - ein
# bestehender, abweichend benannter Collection-Ordner (aeltere Installation) hat
# Vorrang, damit ein Restore auf eine noch nicht migrierte Maschine nicht
# versehentlich einen zweiten, leeren Collection-Ordner anlegt.
CARDDAV_USER=$(ls "$DATA_DIR/radicale/collection-root" 2>/dev/null | head -1)
if [ -z "$CARDDAV_USER" ]; then
  CARDDAV_USER="pas"
  echo "  (kein bestehender Collection-Ordner gefunden, verwende '$CARDDAV_USER')"
else
  echo "  gefunden: $CARDDAV_USER"
fi

COLL="$DATA_DIR/radicale/collection-root/$CARDDAV_USER/kontakte"
mkdir -p "$COLL"
# Alte (leere/veraltete) Karten + Radicale-Cache entfernen, damit Radicale beim
# naechsten Start sauber neu indiziert.
rm -f "$COLL"/*.vcf
rm -rf "$COLL/.Radicale.cache"
cp "$WORK/kontakte-vcf/"*.vcf "$COLL/"
rm -rf "$WORK"

# Radicale erkennt ein Verzeichnis nur dann als CardDAV-Adressbuch (statt als
# generische WebDAV-Collection), wenn .Radicale.props den Tag VADDRESSBOOK
# enthaelt. Ein reines mkdir (wie oben) legt diese Datei NICHT an - normalerweise
# entsteht sie erst durch Radicales eigene MKCOL-Verarbeitung (siehe
# sync/radicale.py _MKCOL_BODY). Ohne sie meldet PROPFIND den Ordner zwar mit
# 207 OK, aber ohne CR:addressbook-resourcetype - macOS Kontakte.app erkennt ihn
# dann bei der Discovery nicht als synchronisierbares Adressbuch und sendet nie
# einen REPORT (das Symptom: Verbindung klappt, Kontakte bleiben dauerhaft leer).
if [ ! -f "$COLL/.Radicale.props" ]; then
  printf '{"D:displayname": "Rubrica", "tag": "VADDRESSBOOK"}' > "$COLL/.Radicale.props"
  echo "→ .Radicale.props angelegt (fehlte - Adressbuch-Kennzeichnung nachgetragen)"
fi

echo "→ Rubrica-Dienste neu starten…"
launchctl bootstrap "gui/$UIDN" "$LA_DIR/ch.strut.rubrica.server.plist" 2>/dev/null || true
launchctl bootstrap "gui/$UIDN" "$LA_DIR/ch.strut.rubrica.radicale.plist" 2>/dev/null || true
sleep 2

echo
echo "=== Ergebnis ==="
launchctl list | grep rubrica || echo "(Dienste nicht sichtbar - ggf. manuell pruefen)"
KONTAKTE=$(sqlite3 "$DATA_DIR/rubrica.db" "SELECT COUNT(*) FROM kontakte;" 2>/dev/null || echo "?")
ORDNER=$(sqlite3 "$DATA_DIR/rubrica.db" "SELECT COUNT(*) FROM projekte;" 2>/dev/null || echo "?")
KARTEN=$(find "$COLL" -maxdepth 1 -name '*.vcf' 2>/dev/null | wc -l | tr -d ' ')
echo "Kontakte: $KONTAKTE, Ordner: $ORDNER, Radicale-Karten: $KARTEN"
echo "✓ Fertig."
