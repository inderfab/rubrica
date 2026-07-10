"""Einmaliges Nachtrags-Skript: pusht alle bestehenden Kontakte/Ordner nach Radicale.

Sinnvoll direkt nach dem erstmaligen Aktivieren von radicale.enabled (config.yaml),
damit bereits vorhandene Datensaetze (die vor der Aktivierung importiert wurden)
nachtraeglich synchronisiert werden. Danach uebernimmt die App den Sync automatisch
bei jeder Aenderung (siehe sync/radicale.py, web/contacts.py, web/folders.py).

Aufruf: .venv/bin/python scripts/sync_alle_nach_radicale.py
"""
from __future__ import annotations

from db.connection import get_connection
from sync import radicale


def main():
    conn = get_connection()
    try:
        kontakt_ids = [row["id"] for row in conn.execute("SELECT id FROM kontakte")]
        projekt_ids = [row["id"] for row in conn.execute("SELECT id FROM projekte")]

        for kontakt_id in kontakt_ids:
            radicale.push_kontakt(conn, kontakt_id)
        print(f"{len(kontakt_ids)} Kontakte gepusht.")

        for projekt_id in projekt_ids:
            radicale.push_projekt(conn, projekt_id)
        print(f"{len(projekt_ids)} Ordner gepusht.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
