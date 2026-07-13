"""Schreibt/aktualisiert die Radicale-htpasswd-Datei (Server-seitige Authentifizierung).

WICHTIG - zwei getrennte Passwoerter, die synchron bleiben muessen:
  1. config.yaml -> radicale.password: das Passwort, das Rubrica als CLIENT beim
     Pushen sendet (und das der Nutzer in Kontakte.app eintraegt).
  2. radicale-htpasswd: die Datei, gegen die der Radicale-SERVER eingehende Logins
     prueft (sowohl von Kontakte.app als auch von Rubrica selbst).

Wird nur (1) geaendert, schlaegt jeder Login fehl ("Accountname/Passwort konnte nicht
ueberprueft werden" in Kontakte.app). Deshalb ruft die Einstellungen-Seite beim Speichern
eines Radicale-Passworts immer auch diese Funktion auf, damit beide Seiten uebereinstimmen.

Radicale liest die htpasswd-Datei pro Anfrage bzw. bei mtime-Aenderung neu ein (siehe
radicale/auth/htpasswd.py) - ein Neustart ist nach dem Schreiben nicht noetig.
"""
from __future__ import annotations

from pathlib import Path

import bcrypt

from config import settings

HTPASSWD_DATEINAME = "radicale-htpasswd"


def htpasswd_pfad() -> Path:
    return settings.daten_verzeichnis() / HTPASSWD_DATEINAME


def set_password(benutzer: str, passwort: str) -> None:
    """Setzt den bcrypt-Hash fuer `benutzer` in der htpasswd-Datei. Bestehende
    Eintraege anderer Benutzer bleiben erhalten; ein vorhandener Eintrag desselben
    Benutzers wird ersetzt."""
    if not benutzer or not passwort:
        return
    hash_ = bcrypt.hashpw(passwort.encode("utf-8"), bcrypt.gensalt()).decode("ascii")

    pfad = htpasswd_pfad()
    zeilen = []
    if pfad.exists():
        zeilen = [
            z for z in pfad.read_text(encoding="utf-8").splitlines()
            if z and not z.startswith(f"{benutzer}:")
        ]
    zeilen.append(f"{benutzer}:{hash_}")

    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    pfad.chmod(0o600)
