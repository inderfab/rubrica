"""Phase 4 (Vorstufe): liest bereits von Archivio text-extrahierte E-Mail-Signaturen
und erzeugt daraus KANDIDATEN fuer die Review-Queue (vorschlaege, quelle='archivio').

Schreibt selbst NICHTS in die DB (reiner Lesevorgang auf Archivios SQLite, read-only
geoeffnet) - das eigentliche Anlegen der Vorschlaege passiert in web/archivio.py ueber
db.queries.create_vorschlag, exakt wie bei jedem anderen Import (siehe
docs/konzept.md Abschnitt 5.5/9: "nie automatisches Ueberschreiben").

Bewusst auf hohe Praezision statt Vollstaendigkeit ausgelegt, um eine Explosion
der Kontaktzahl zu vermeiden (siehe Konzept-Abschnitt 11, Strategische Richtung).
Nutzer-Feedback nach dem ersten Live-Test: Kandidaten waren zu oft unvollstaendig
(Funktion statt Name, fehlende E-Mail, Newsletter-Text als Firma, unplausible
Telefonnummern) und bereits bestehende Kontakte tauchten erneut auf. Ursache fuer
die Luecken teilweise strukturell: Archivios eigener Mail-Scanner (mail_scanner.py,
_strip_signature) schneidet bei IMAP-gescannten Mails ALLES nach einer Grussformel
("Freundliche Gruesse" etc.) ab - genau der Teil mit Name/Telefon/Mail geht dabei
unwiederbringlich verloren, bevor der Text ueberhaupt in Archivios DB landet. Nicht
in Rubrica behebbar (liegt in Archivios eigener Pipeline). Gegenmassnahmen hier:
  - nur Absender mit mindestens `min_mails` E-Mails (Indiz fuer echte Korrespondenz)
  - bis zu `MAX_VERSUCHE_PRO_ABSENDER` Mails je Absender probieren, nicht nur die
    neueste - falls eine Mail durch die Signatur-Kappung unvollstaendig ist, liefert
    vielleicht eine andere Mail desselben Absenders ein vollstaendiges Ergebnis
  - STRENGE Vollstaendigkeitspruefung: Name (Vor- UND Nachname), Firma, mindestens
    eine Telefonnummer UND eine E-Mail muessen ALLE vorhanden sein, sonst kein
    Vorschlag - lieber wenige, aber vollstaendige Vorschlaege
  - Dublettenpruefung gegen bestehende Kontakte per E-Mail, Name ODER Telefonnummer
    (nicht nur E-Mail wie zuvor - reicht sonst nicht, wenn die Signatur eine andere
    Adresse liefert als im Bestand hinterlegt)
"""
from __future__ import annotations

import json
import re
import sqlite3

from importer.signatur import parse_signatur

_EMAIL_EINFACH = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_VERSUCHE_PRO_ABSENDER = 5


def _letzte_zeilen(text: str, n: int = 14) -> str:
    zeilen = (text or "").replace("\r\n", "\n").split("\n")
    while zeilen and not zeilen[-1].strip():
        zeilen.pop()
    return "\n".join(zeilen[-n:])


def _normalisiere_telefon(nummer: str) -> str:
    return re.sub(r"\D", "", nummer).lstrip("0")


def _ist_vollstaendig(daten: dict) -> bool:
    return bool(
        daten["vorname"] and daten["nachname"] and daten["firma"]
        and daten["telefonnummern"] and daten["emails"]
    )


class _BestehenderBestand:
    """Vorberechnete Indizes des bestehenden Kontaktbestands fuer die
    Dublettenpruefung (E-Mail, Name, Telefonnummer) - UND bereits per Archivio-
    Vorschau entschiedene Vorschlaege (egal ob uebernommen oder abgelehnt), damit
    einmal abgelehnte Kandidaten nicht erneut auftauchen."""

    def __init__(self, conn: sqlite3.Connection):
        self.mails = {r["email"].lower() for r in conn.execute("SELECT email FROM emails")}
        self.namen = {
            (r["vorname"].strip().lower(), r["nachname"].strip().lower())
            for r in conn.execute("SELECT vorname, nachname FROM kontakte")
            if r["vorname"].strip() or r["nachname"].strip()
        }
        self.telefone = {
            _normalisiere_telefon(r["nummer"]) for r in conn.execute("SELECT nummer FROM telefonnummern")
        }
        for row in conn.execute("SELECT rohdaten FROM vorschlaege WHERE quelle = 'archivio'"):
            try:
                rohdaten = json.loads(row["rohdaten"])
            except (TypeError, ValueError):
                continue
            for e in rohdaten.get("emails", []):
                if e.get("email"):
                    self.mails.add(e["email"].lower())

    def ist_dublette(self, daten: dict) -> bool:
        mail_adressen = {e["email"].lower() for e in daten["emails"]}
        if mail_adressen & self.mails:
            return True
        name = (daten["vorname"].strip().lower(), daten["nachname"].strip().lower())
        if name in self.namen:
            return True
        for t in daten["telefonnummern"]:
            if _normalisiere_telefon(t["nummer"]) in self.telefone:
                return True
        return False


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

    bestand = _BestehenderBestand(rubrica_conn)
    kandidaten = []
    for sender, inhalte in pro_absender.items():
        if len(inhalte) < min_mails:
            continue

        daten = None
        for inhalt in inhalte[:MAX_VERSUCHE_PRO_ABSENDER]:
            versuch = parse_signatur(_letzte_zeilen(inhalt))
            if not versuch["emails"] and _EMAIL_EINFACH.match(sender):
                versuch["emails"] = [{"typ": "arbeit", "email": sender}]
            if _ist_vollstaendig(versuch):
                daten = versuch
                break
        if daten is None:
            continue  # keine der Mails dieses Absenders lieferte ein vollstaendiges Ergebnis

        if bestand.ist_dublette(daten):
            continue

        daten["anzahl_mails"] = len(inhalte)
        kandidaten.append(daten)

    return kandidaten
