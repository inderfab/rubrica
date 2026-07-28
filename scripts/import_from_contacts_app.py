"""Einmaliges Migrationsskript: importiert alle Kontakte + Gruppen aus Kontakte.app
in Rubrica. Fuer bestehende Installationen ohne Setup-Assistent (Kernlogik in
importer/contacts_app.py, wird auch von Schritt 4 des Setup-Assistenten genutzt,
siehe web/setup.py). Siehe docs/konzept.md Abschnitt 5.6.

Aufruf: .venv/bin/python scripts/import_from_contacts_app.py
"""
from __future__ import annotations

from db.connection import get_connection, init_schema
from importer.contacts_app import importiere_aus_kontakte_app
from sync import radicale


def main():
    print("Lese Kontakte + Gruppen aus Kontakte.app…")
    init_schema()
    conn = get_connection()
    try:
        ergebnis = importiere_aus_kontakte_app(conn)
        kontakt_ids = ergebnis.pop("kontakt_ids", [])
        print(f"{ergebnis['gefunden']} Kontakte, {ergebnis['gruppen_gefunden']} Gruppen gefunden.")
        if ergebnis["ohne_uid"]:
            print(f"Hinweis: {ergebnis['ohne_uid']} Kontakte ohne X-ABUID (Gruppenzuordnung fuer diese nicht moeglich).")
        print(f"{ergebnis['importiert']} Kontakte importiert (direkt angelegt oder mit bestehendem Kontakt "
              f"zusammengefuehrt), {ergebnis['fehler']} Eintraege uebersprungen.")
        print(f"Rubrica enthaelt jetzt {ergebnis['kontakte_gesamt']} Kontakte in {ergebnis['ordner_gesamt']} Ordnern.")
        print("Synchronisiere nach Radicale…")
        for kontakt_id in kontakt_ids:
            radicale.push_kontakt_mit_ordnern(conn, kontakt_id)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
