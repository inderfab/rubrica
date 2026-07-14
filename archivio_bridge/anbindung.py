"""Phase 4: liest Archivios Signatur-DB (Tabelle `signatur_quelle`: Absender, Postfach,
voller Mailtext, Status) und erzeugt daraus KANDIDATEN fuer die Review-Queue
(vorschlaege, quelle='archivio').

Anders als eine reine Nur-Lese-Anbindung schreibt dieses Modul bewusst den `status`
zurueck in Archivios DB (pending -> uebernommen/abgelehnt) - das ist die vom Nutzer
selbst vorgesehene Nutzung dieser Spalte (siehe docs/konzept.md), nicht Rubricas
Kontakt-Prinzip von "nie automatisches Ueberschreiben" (das betrifft ausschliesslich
Kontaktdaten, nicht diese Verarbeitungs-Markierung). Zweck: verhindert, dass bereits
entschiedene Absender bei jedem Scan erneut vorgeschlagen werden, waehrend Absender mit
noch zu wenig Mails bewusst "pending" bleiben (kuenftige Mails koennen sie ergaenzen).

Bewusst auf hohe Praezision statt Vollstaendigkeit ausgelegt, um eine Explosion der
Kontaktzahl zu vermeiden (siehe Konzept-Abschnitt 11, Strategische Richtung):
  - eigene Mitarbeiter (EIGENE_DOMAIN) werden nie als Kandidat vorgeschlagen
  - nur Absender mit mindestens `min_mails` E-Mails (Indiz fuer echte Korrespondenz)
  - bis zu `MAX_VERSUCHE_PRO_ABSENDER` Mails je Absender probieren, nicht nur die
    neueste - falls eine Mail kein vollstaendiges Ergebnis liefert, vielleicht eine
    andere Mail desselben Absenders
  - STRENGE Vollstaendigkeitspruefung: Name (Vor- UND Nachname), Firma, mindestens
    eine Telefonnummer UND eine E-Mail muessen ALLE vorhanden sein
  - Dublettenpruefung gegen bestehende Kontakte per E-Mail, Name ODER Telefonnummer

Wichtig fuer die Signatur-Erkennung: Archivio liefert jetzt den VOLLEN Mailtext,
nicht mehr eine bereits auf eine einzelne Nachricht gekuerzte Version - bei einem
laengeren Thread stehen darin mehrere zitierte fruehere Nachrichten samt eigener
Signaturen. Eine simple "letzte N Zeilen"-Heuristik wuerde dabei oft die Signatur
der AELTESTEN zitierten Person erwischen statt der des tatsaechlichen Absenders
(am echten Testdatensatz verifiziert). Deshalb wird zuerst der zitierte Verlauf
abgeschnitten (`_ohne_zitat`), bevor die bestehende "letzte Zeilen"-Heuristik
darauf angewendet wird.
"""
from __future__ import annotations

import json
import re
import sqlite3

from db import queries
from importer.signatur import parse_signatur

_EMAIL_EINFACH = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Automatisierte Systemadressen sind nie ein echter Korrespondenzpartner - auch wenn
# eine solche Mail (z.B. eine Plot-/Druckauftrags-Benachrichtigung) zufaellig einen
# vollstaendig aussehenden Namen/Telefon/E-Mail im Text enthaelt (am echten
# Testdatensatz beobachtet: "no-reply@plotjet.com" lieferte einen Kandidaten mit den
# Daten des internen Bestellers aus der Benachrichtigungsvorlage).
_AUTOMATISIERTER_ABSENDER = re.compile(r"^(no-?reply|donotreply|mailer-daemon|postmaster)@", re.IGNORECASE)

MAX_VERSUCHE_PRO_ABSENDER = 5

# Bespoke fuer Strut Architekten AG (siehe CLAUDE.md) - eigene Mitarbeiter sind nie
# Import-Kandidaten (sie sind bereits als Kontakte erfasst bzw. kein Adressbuch-Eintrag).
EIGENE_DOMAIN = "@strut.ch"

# Zeilen, an denen zitierter Mailverlauf beginnt (Outlook-Stil "Von:/Gesendet:/An:/
# Betreff:", Apple-Mail/Gmail-Stil "Am ... schrieb ...:", englische Pendants,
# klassische ">"-Zitatzeilen, "-----Urspruengliche Nachricht-----").
_ZITAT_ZEILEN_MUSTER = [
    re.compile(r"^Von:\s", re.IGNORECASE),
    re.compile(r"^Gesendet:\s", re.IGNORECASE),
    re.compile(r"^From:\s", re.IGNORECASE),
    re.compile(r"^Sent:\s", re.IGNORECASE),
    re.compile(r"^-{3,}\s*(Urspr(ü|u)ngliche Nachricht|Original Message)\s*-{3,}", re.IGNORECASE),
    re.compile(r"^Am\s.+\sschrieb\s.+:\s*$", re.IGNORECASE),
    re.compile(r"^On\s.+\swrote:\s*$", re.IGNORECASE),
    re.compile(r"^>"),
]


def _ohne_zitat(text: str) -> str:
    """Schneidet alles ab der ersten Zitat-Zeile ab - liefert nur die aktuelle
    Nachricht (inkl. deren eigener Signatur), nicht den ganzen Thread-Verlauf."""
    zeilen = (text or "").replace("\r\n", "\n").split("\n")
    for i, zeile in enumerate(zeilen):
        z = zeile.strip()
        if any(muster.match(z) for muster in _ZITAT_ZEILEN_MUSTER):
            return "\n".join(zeilen[:i])
    return text


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


def liste_postfaecher(signatur_db_pfad: str) -> list:
    """Alle im Postfach vorkommenden (postfach, projekt)-Paare - Grundlage fuer die
    Mehrfachauswahl auf der Archivio-Import-Seite und die Postfach->Ordner-Zuordnung."""
    conn = sqlite3.connect(f"file:{signatur_db_pfad}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT DISTINCT postfach, projekt FROM signatur_quelle "
            "WHERE postfach != '' ORDER BY postfach"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def markiere_status(signatur_db_pfad: str, absender_email: str, status: str) -> None:
    """Setzt den Status aller aktuell 'pending' Mails eines Absenders (nach
    Bestaetigen/Ablehnen in der Review-Queue) - verhindert, dass er beim naechsten
    Scan erneut als Kandidat auftaucht."""
    conn = sqlite3.connect(signatur_db_pfad)
    try:
        conn.execute(
            "UPDATE signatur_quelle SET status = ?, "
            "status_updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
            "WHERE absender_email = ? AND status = 'pending'",
            (status, absender_email),
        )
        conn.commit()
    finally:
        conn.close()


def hole_kandidaten(signatur_db_pfad: str, rubrica_conn: sqlite3.Connection,
                     min_mails: int = 2, postfaecher: list | None = None) -> list:
    """Liefert eine Liste von Kandidaten-Dicts (kompatibel zu
    db.queries.create_vorschlag, plus `absender_email` fuer die spaetere Status-
    Markierung beim Bestaetigen/Ablehnen). Mails ohne verwertbares Ergebnis bleiben
    'pending'; erkannte Dubletten werden sofort als 'abgelehnt' markiert."""
    conn = sqlite3.connect(signatur_db_pfad)
    conn.row_factory = sqlite3.Row
    try:
        where = ["status = 'pending'", "absender_email != ''", "absender_email NOT LIKE ?"]
        params: list = [f"%{EIGENE_DOMAIN}"]
        if postfaecher:
            platzhalter = ",".join("?" * len(postfaecher))
            where.append(f"postfach IN ({platzhalter})")
            params.extend(postfaecher)

        rows = conn.execute(
            f"SELECT id, absender_email, postfach, text FROM signatur_quelle "
            f"WHERE {' AND '.join(where)} ORDER BY datum DESC",
            params,
        ).fetchall()

        pro_absender: dict = {}
        for r in rows:
            pro_absender.setdefault(r["absender_email"], []).append(r)

        postfach_ordner = queries.postfach_zuordnungen(rubrica_conn)
        bestand = _BestehenderBestand(rubrica_conn)
        kandidaten = []

        for absender_email, eintraege in pro_absender.items():
            if _AUTOMATISIERTER_ABSENDER.match(absender_email):
                continue  # automatisierte Systemadresse, nie ein echter Korrespondenzpartner
            if len(eintraege) < min_mails:
                continue  # bleibt 'pending' - eine kuenftige Mail kann das noch aendern

            daten = None
            for eintrag in eintraege[:MAX_VERSUCHE_PRO_ABSENDER]:
                bereinigt = _ohne_zitat(eintrag["text"])
                versuch = parse_signatur(_letzte_zeilen(bereinigt))
                if not versuch["emails"] and _EMAIL_EINFACH.match(absender_email):
                    versuch["emails"] = [{"typ": "Direkt", "email": absender_email}]
                if _ist_vollstaendig(versuch):
                    daten = versuch
                    break

            if daten is None:
                continue  # bleibt 'pending' - keine der versuchten Mails reichte

            if bestand.ist_dublette(daten):
                # Schon ein bekannter Kontakt: kein Vorschlag noetig, aber auch nicht
                # bei jedem weiteren Scan erneut pruefen.
                conn.executemany(
                    "UPDATE signatur_quelle SET status = 'abgelehnt', "
                    "status_updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
                    [(e["id"],) for e in eintraege],
                )
                conn.commit()
                continue

            ordner = {
                postfach_ordner[e["postfach"]]["name"]
                for e in eintraege if e["postfach"] in postfach_ordner
            }
            daten["anzahl_mails"] = len(eintraege)
            daten["gruppen_als_ordner"] = sorted(ordner)
            daten["absender_email"] = absender_email
            kandidaten.append(daten)

        return kandidaten
    finally:
        conn.close()
