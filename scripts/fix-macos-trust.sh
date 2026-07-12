#!/bin/bash
# Markiert die lokale Rubrica-CA systemweit als vertrauenswuerdig, damit macOS
# Kontakte.app den CardDAV-Server (Radicale) akzeptiert und synchronisiert.
#
# Hintergrund: Der macOS-Kontakte-Sync-Daemon validiert das TLS-Zertifikat strikt.
# Ohne vertrauenswuerdige CA macht macOS nach dem Verbinden nur die Discovery, aber
# nie einen REPORT - die Kontakte bleiben leer (siehe docs/konzept.md Abschnitt 9).
# Auf einer frisch per .pkg installierten Maschine erledigt das bereits der
# Postinstall automatisch; dieses Skript ist fuer bestehende/manuelle Installationen.
#
# Aufruf:  sudo bash scripts/fix-macos-trust.sh
set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo ausfuehren:  sudo bash scripts/fix-macos-trust.sh" >&2
  exit 1
fi

REAL_USER="${SUDO_USER:-$(stat -f '%Su' /dev/console)}"
CA="/Users/$REAL_USER/Library/Application Support/Rubrica/radicale-tls/ca-cert.pem"

if [ ! -f "$CA" ]; then
  echo "CA nicht gefunden: $CA" >&2
  echo "Laeuft der Radicale-Dienst? Er erzeugt das Zertifikat beim ersten Start." >&2
  exit 1
fi

security add-trusted-cert -d -r trustRoot -p ssl \
  -k /Library/Keychains/System.keychain "$CA"

echo "OK: Rubrica-CA ist jetzt systemweit vertrauenswuerdig."
echo "Naechster Schritt: alten CardDAV-Account in Kontakte.app entfernen und neu anlegen."
