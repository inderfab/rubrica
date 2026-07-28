"""Einmaliges Migrationsskript: importiert alle Kontakte + Gruppen aus Kontakte.app
in Rubrica. Fuer bestehende Installationen ohne Setup-Assistent (Kernlogik in
importer/contacts_app.py, wird auch von Schritt 4 des Setup-Assistenten genutzt,
siehe web/setup.py). Siehe docs/konzept.md Abschnitt 5.6.

Aufruf: .venv/bin/python scripts/import_from_contacts_app.py
"""
from __future__ import annotations

from db.connection import get_connection, init_schema
from web.shared import importiere_kontakte_app_und_synchronisiere

_LETZTE_PHASE = None


def _fortschritt(phase, verarbeitet, gesamt):
    global _LETZTE_PHASE
    if phase != _LETZTE_PHASE:
        print({"lese": "Lese Kontakte + Gruppen aus Kontakte.app…",
               "importiere": "Importiere…", "synchronisiere": "Synchronisiere nach Radicale…"}[phase])
        _LETZTE_PHASE = phase
    if gesamt and verarbeitet % 100 == 0:
        print(f"  {verarbeitet} von {gesamt}…")


def main():
    init_schema()
    conn = get_connection()
    try:
        ergebnis = importiere_kontakte_app_und_synchronisiere(conn, fortschritt_callback=_fortschritt)
        print(f"{ergebnis['gefunden']} Kontakte, {ergebnis['gruppen_gefunden']} Gruppen gefunden.")
        if ergebnis["ohne_uid"]:
            print(f"Hinweis: {ergebnis['ohne_uid']} Kontakte ohne X-ABUID (Gruppenzuordnung fuer diese nicht moeglich).")
        print(f"{ergebnis['importiert']} Kontakte importiert (direkt angelegt oder mit bestehendem Kontakt "
              f"zusammengefuehrt), {ergebnis['fehler']} Eintraege uebersprungen"
              f"{' (' + ', '.join(f'{n}x {t}' for t, n in ergebnis['fehler_typen'].items()) + ')' if ergebnis['fehler_typen'] else ''}.")
        print(f"Rubrica enthaelt jetzt {ergebnis['kontakte_gesamt']} Kontakte in {ergebnis['ordner_gesamt']} Ordnern.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
