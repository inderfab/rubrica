"""Einmaliges Nachtrags-Skript: gleicht alle Kontakte/Ordner mit Radicale ab.

Sinnvoll, um bereits vorhandene Datensaetze nachtraeglich zu synchronisieren
(z.B. nach einem Import mit deaktiviertem/fehlerhaftem Sync). Danach uebernimmt
die App den Sync automatisch bei jeder Aenderung. Dieselbe Logik steht in der
Weboberflaeche unter Einstellungen -> "Jetzt alles neu synchronisieren".

Aufruf: .venv/bin/python scripts/sync_alle_nach_radicale.py
"""
from __future__ import annotations

from db.connection import get_connection
from sync import radicale


def main():
    conn = get_connection()
    try:
        ergebnis = radicale.sync_alle(conn)
    finally:
        conn.close()

    if not ergebnis["aktiv"]:
        print("Radicale nicht konfiguriert - nichts synchronisiert.")
        return
    print(f"{ergebnis['kontakte']} Kontakte gepusht.")
    print(f"{ergebnis['ordner']} Ordner gepusht.")
    print(f"{ergebnis['entfernt']} verwaiste Eintraege entfernt.")
    for fehler in ergebnis["fehler"]:
        print(f"  Fehler: {fehler}")


if __name__ == "__main__":
    main()
