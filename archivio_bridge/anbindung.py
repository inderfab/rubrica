"""Phase 4 (Vorstufe): liest bereits von Archivio text-extrahierte E-Mail-Signaturen
und erzeugt daraus KANDIDATEN fuer die Review-Queue (vorschlaege, quelle='archivio').

Schreibt selbst NICHTS in die DB (reiner Lesevorgang auf Archivios SQLite, read-only
geoeffnet) - das eigentliche Anlegen der Vorschlaege passiert in web/archivio.py ueber
db.queries.create_vorschlag, exakt wie bei jedem anderen Import (siehe
docs/konzept.md Abschnitt 5.5/9: "nie automatisches Ueberschreiben").

Bewusst auf hohe Praezision statt Vollstaendigkeit ausgelegt, um eine Explosion
der Kontaktzahl zu vermeiden (siehe Konzept-Abschnitt 11, Strategische Richtung):
  - nur Absender mit mindestens `min_mails` E-Mails (Indiz fuer echte Korrespondenz,
    nicht nur eine einzelne Zufalls-Mail)
  - nur wenn die geparste Signatur sowohl Telefonnummer ALS AUCH Firma enthaelt
  - bereits als E-Mail-Adresse in Rubrica vorhandene Kontakte werden uebersprungen
"""
from __future__ import annotations

import re
import sqlite3

from importer.signatur import parse_signatur

_EMAIL_EINFACH = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _letzte_zeilen(text: str, n: int = 14) -> str:
    zeilen = (text or "").replace("\r\n", "\n").split("\n")
    while zeilen and not zeilen[-1].strip():
        zeilen.pop()
    return "\n".join(zeilen[-n:])


def _bestehende_mailadressen(rubrica_conn: sqlite3.Connection) -> set:
    return {r["email"].lower() for r in rubrica_conn.execute("SELECT email FROM emails")}


def hole_kandidaten(archivio_db_pfad: str, rubrica_conn: sqlite3.Connection,
                     min_mails: int = 2) -> list:
    """Liefert eine Liste von Kandidaten-Dicts (kompatibel zu
    db.queries.create_vorschlag). Reiner Lesevorgang, schreibt nichts."""
    conn = sqlite3.connect(f"file:{archivio_db_pfad}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT m.sender AS sender, dc.content AS content
            FROM mails m
            JOIN documents d ON d.id = m.document_id
            JOIN document_content dc ON dc.document_id = m.document_id
            WHERE d.source_type = 'email' AND m.sender != ''
            ORDER BY m.date DESC
        """).fetchall()
    finally:
        conn.close()

    pro_absender = {}
    for r in rows:
        pro_absender.setdefault(r["sender"], []).append(r["content"])

    bestehende = _bestehende_mailadressen(rubrica_conn)
    kandidaten = []
    for sender, inhalte in pro_absender.items():
        if len(inhalte) < min_mails:
            continue
        # Neueste Mail dieses Absenders (Query ist nach Datum absteigend sortiert,
        # daher ist der erste Eintrag pro Absender-Gruppe die aktuellste Signatur).
        signatur = _letzte_zeilen(inhalte[0])
        daten = parse_signatur(signatur)
        if not daten["telefonnummern"] or not daten["firma"]:
            continue

        mail_adressen = {e["email"].lower() for e in daten["emails"]}
        if not mail_adressen and _EMAIL_EINFACH.match(sender):
            daten["emails"] = [{"typ": "arbeit", "email": sender}]
            mail_adressen = {sender.lower()}
        if mail_adressen and (mail_adressen & bestehende):
            continue  # schon in Rubrica vorhanden - kein Vorschlag noetig

        daten["anzahl_mails"] = len(inhalte)
        kandidaten.append(daten)

    return kandidaten
