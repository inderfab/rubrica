"""Diagnose-Skript: findet Kontaktaenderungen aus Kontakte.app, die vermutlich durch
den sync_alle-Wettlaufeffekt stillschweigend verworfen statt bewusst abgelehnt wurden.

Hintergrund: sync_alle() erkennt eine Aenderung aus Kontakte.app und legt dafuer einen
Vorschlag an (status='offen'), pusht aber im selben Durchlauf jeden Kontakt unbedingt
aus der Datenbank zurueck - das ueberschreibt die gerade erkannte, noch unbestaetigte
Aenderung wieder mit dem alten Stand. Der naechste Abgleich sieht keinen Unterschied
mehr und zieht den Vorschlag automatisch zurueck (status='abgelehnt') - ununterscheidbar
von einer bewussten Ablehnung im Buero.

Dieses Skript unterscheidet die Faelle: ein abgelehnter Aenderungs-Vorschlag gilt als
vermutlich verworfen, wenn der aktuelle Datenbankwert des betroffenen Felds noch exakt
dem "alt"-Stand aus dem Vorschlag entspricht (die Korrektur ist also nie angekommen)
UND kein spaeterer, bestaetigter Vorschlag fuer denselben Kontakt/dasselbe Feld existiert.

Aufruf (aus dem Projektwurzelverzeichnis, PYTHONPATH auf "." wegen des scripts/-
Unterordners): PYTHONPATH=. .venv/bin/python scripts/pruefe_verworfene_aenderungen.py

Auf einer installierten .pkg-Instanz statt des venv das eingebettete Python nutzen,
mit PYTHONPATH auf den Resources-Ordner der App:
  RESOURCES="/Applications/Rubrica Server.app/Contents/Resources"
  PYTHONPATH="$RESOURCES" RUBRICA_DATA_DIR="$HOME/Library/Application Support/Rubrica" \\
    "$RESOURCES/rubrica-python-$(uname -m)/bin/python3" scripts/pruefe_verworfene_aenderungen.py
"""
from __future__ import annotations

import json

from db.connection import get_connection
from db import queries
from kontakte_app_intake import _FELD_BESCHRIFTUNG, _lesbar

_FELD_KEY = {label: key for key, label in _FELD_BESCHRIFTUNG.items()}


def _norm(text: str) -> str:
    """Grobe Normalisierung fuer den Textvergleich: Gross-/Kleinschreibung und
    Mehrfach-Leerzeichen sind seit der Kategorien-Umstellung (arbeit -> Arbeit)
    kein verlaesslicher Unterschied mehr."""
    return " ".join((text or "").split()).lower()


def main():
    conn = get_connection()
    try:
        zeilen = conn.execute(
            "SELECT * FROM vorschlaege WHERE quelle = 'kontakte_app' AND status = 'abgelehnt' "
            "ORDER BY kontakt_id, created_at"
        ).fetchall()

        # Fuer den "spaeter doch bestaetigt"-Check: alle bestaetigten Aenderungen je Kontakt,
        # mit Zeitpunkt, damit sich frueher/spaeter vergleichen laesst.
        bestaetigte = [
            {"kontakt_id": b["kontakt_id"], "created_at": b["created_at"],
             "geaenderte_felder": json.loads(b["rohdaten"]).get("geaenderte_felder", {})}
            for b in conn.execute(
                "SELECT kontakt_id, created_at, rohdaten FROM vorschlaege "
                "WHERE quelle = 'kontakte_app' AND status = 'bestaetigt'"
            ).fetchall()
        ]

        gefunden = 0
        for row in zeilen:
            vorschlag = dict(row)
            rohdaten = json.loads(vorschlag["rohdaten"])
            if rohdaten.get("typ") != "aenderung":
                continue
            kontakt_id = vorschlag["kontakt_id"]
            kontakt = queries.get_kontakt(conn, kontakt_id) if kontakt_id else None
            if kontakt is None:
                continue

            for u in rohdaten.get("unterschiede", []):
                feld_key = _FELD_KEY.get(u["feld"])
                if feld_key is None:
                    continue
                aktuell_lesbar = _lesbar(feld_key, kontakt.get(feld_key))
                # "neu" hat Vorrang: entspricht der aktuelle Stand der vorgeschlagenen
                # Fassung, ist nichts verloren - unabhaengig davon, ob "alt" wegen der
                # Kategorien-Umstellung (arbeit -> Arbeit) nicht mehr exakt passt.
                if _norm(aktuell_lesbar) == _norm(u["neu"]):
                    continue
                if _norm(aktuell_lesbar) != _norm(u["alt"]):
                    continue  # weder alt noch neu - seither anders geaendert, kein klarer Fall

                spaeter_bestaetigt = any(
                    b["kontakt_id"] == kontakt_id and b["created_at"] > vorschlag["created_at"]
                    and feld_key in b["geaenderte_felder"]
                    for b in bestaetigte
                )
                if spaeter_bestaetigt:
                    continue  # eine neuere Fassung DESSELBEN Felds wurde danach bewusst uebernommen

                gefunden += 1
                name = f"{kontakt['vorname']} {kontakt['nachname']}".strip() or kontakt["firma"]
                print(f"- {name} (Kontakt-ID {kontakt_id}): {u['feld']}")
                print(f"    verworfen am {vorschlag['created_at']}")
                print(f"    aktuell noch: {u['alt']}")
                print(f"    waere gewesen: {u['neu']}")
                print()

        if gefunden == 0:
            print("Keine Faelle gefunden.")
        else:
            print(f"{gefunden} vermutlich stillschweigend verworfene Aenderung(en) gefunden.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
