"""vCard-Import (Phase 0): parst .vcf-Exporte aus Kontakte.app und mappt sie
auf das Rubrica-Datenmodell. Legt erkannte Kontakte direkt an bzw. mergt sie in
bestehende (nie destruktiv, siehe queries.merge_kontakt) - siehe web/imports.py."""
from __future__ import annotations

import re
import sqlite3

import vobject

from db import queries


def _values(vcard, name: str) -> list:
    return list(getattr(vcard, f"{name}_list", []) or [])


def _parse_name(vcard) -> tuple[str, str]:
    if hasattr(vcard, "n"):
        n = vcard.n.value
        return (n.given or "").strip(), (n.family or "").strip()
    if hasattr(vcard, "fn"):
        parts = vcard.fn.value.strip().split(" ", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0], ""
    return "", ""


def _typ_von(prop) -> str:
    typ = getattr(prop, "type_param", None)
    if isinstance(typ, list):
        typ = typ[0] if typ else None
    return (typ or "").lower()


# vCard-Importe (v.a. aus Apple Kontakte.app) taggen Telefonnummern/E-Mails
# englisch (work/cell/home) statt mit unseren drei Kategorien Direkt/Privat/
# Allgemein - hier auf die neue Kategorisierung gemappt. Mobile Nummern gelten
# als privat (in der Praxis meist persoenliche Nummern), unbekannte/generische
# Typen (z.B. Apples "internet" fuer alle E-Mails) defaulten zu "Direkt"
# (sichtbar), damit beim Import nichts faelschlich verschwindet.
# Feste Kategorien, identisch zu web/contacts.py TELEFON_TYPEN - importierte vCards
# muessen dieselben Werte liefern, sonst entstuende ueber den Import wieder der
# Wildwuchs, den die Migration 2026-08-06 gerade beseitigt hat.
_TELEFON_TYP_MAPPING = {
    "work": "Direkt", "arbeit": "Direkt", "office": "Direkt", "main": "Direkt",
    "allgemein": "Direkt", "voice": "Direkt",
    "cell": "Direkt Handy", "mobil": "Direkt Handy", "mobile": "Direkt Handy",
    "iphone": "Direkt Handy", "handy": "Direkt Handy", "natel": "Direkt Handy",
    "home": "Privat", "privat": "Privat", "private": "Privat",
}
_EMAIL_TYP_MAPPING = {
    "work": "Direkt", "arbeit": "Direkt", "internet": "Direkt",
    "main": "Allgemein", "allgemein": "Allgemein", "info": "Allgemein",
    "home": "Privat", "privat": "Privat", "private": "Privat",
}


# Adress-Typen wurden bisher NICHT normalisiert - Rubrica schreibt TYPE=ARBEIT,
# Apple gibt beim Zurueckschreiben type=WORK. Dadurch meldete die
# Aenderungserkennung bei jedem Apple-Rueckschreiben eine Adressaenderung, obwohl
# inhaltlich nichts anders war (Nutzer-Meldung). Gleiches Muster wie bei Telefon
# und E-Mail.
_ADRESSE_TYP_MAPPING = {
    "work": "arbeit", "arbeit": "arbeit", "office": "arbeit", "business": "arbeit",
    "home": "privat", "privat": "privat", "private": "privat",
}


def _adresse_typ_normalisieren(rohtyp: str) -> str:
    return _ADRESSE_TYP_MAPPING.get((rohtyp or "").lower(), "arbeit")


def _telefon_typ_normalisieren(rohtyp: str) -> str:
    return _TELEFON_TYP_MAPPING.get(rohtyp.lower(), "Direkt")


def _email_typ_normalisieren(rohtyp: str) -> str:
    return _EMAIL_TYP_MAPPING.get(rohtyp.lower(), "Direkt")


def _parse_kontakt(vcard) -> dict:
    vorname, nachname = _parse_name(vcard)
    firma = vcard.org.value[0] if hasattr(vcard, "org") and vcard.org.value else ""
    rolle = vcard.title.value if hasattr(vcard, "title") else ""
    apple_uid = vcard.uid.value if hasattr(vcard, "uid") else None

    telefonnummern = [
        {"typ": _telefon_typ_normalisieren(_typ_von(tel)), "nummer": tel.value.strip()}
        for tel in _values(vcard, "tel") if tel.value and tel.value.strip()
    ]
    emails = [
        {"typ": _email_typ_normalisieren(_typ_von(mail)), "email": mail.value.strip()}
        for mail in _values(vcard, "email") if mail.value and mail.value.strip()
    ]
    adressen = [
        {
            "typ": _adresse_typ_normalisieren(_typ_von(adr)),
            "strasse": (adr.value.street or "").strip(),
            "plz": (adr.value.code or "").strip(),
            "ort": (adr.value.city or "").strip(),
            "region": (adr.value.region or "").strip(),
            "land": (adr.value.country or "").strip(),
        }
        for adr in _values(vcard, "adr")
        if any([adr.value.street, adr.value.city, adr.value.code])
    ]
    urls = [
        {"typ": _typ_von(url) or "homepage", "url": url.value.strip()}
        for url in _values(vcard, "url") if url.value and url.value.strip()
    ]
    notizen = "\n---\n".join(
        n.value.strip() for n in _values(vcard, "note") if n.value and n.value.strip()
    )

    return {
        "vorname": vorname,
        "nachname": nachname,
        "firma": firma,
        "rolle": rolle,
        "kategorie": "",
        "notizen": notizen,
        "telefonnummern": telefonnummern,
        "emails": emails,
        "adressen": adressen,
        "urls": urls,
        "apple_uid": apple_uid,
    }


def _ist_gruppe(vcard) -> bool:
    kind = getattr(vcard, "x_addressbookserver_kind", None) or getattr(vcard, "kind", None)
    return bool(kind and kind.value.lower() == "group")


def _gruppen_mitglieder_uids(vcard) -> list[str]:
    member_prop = "x_addressbookserver_member_list"
    uids = []
    for member in getattr(vcard, member_prop, []) or []:
        val = member.value
        if val.startswith("urn:uuid:"):
            val = val[len("urn:uuid:"):]
        uids.append(val)
    return uids


def parse_vcf(inhalt: str) -> list[dict]:
    """Parst eine .vcf-Datei (kann mehrere vCards enthalten, inkl. Apple-Gruppen).
    Gibt eine Liste von Kontakt-Dicts zurueck, jeweils mit optionalem Key
    'gruppen' (Namen der Apple-Gruppen, denen der Kontakt angehoert) und
    'gruppen_uids' (Name -> stabile Apple-Gruppen-UID, siehe
    queries.get_or_create_projekt_von_apple_gruppe - macht das Wiedererkennen eines
    in Rubrica umbenannten Ordners bei einem erneuten Import robust)."""
    komponenten = list(vobject.readComponents(inhalt))

    gruppen_namen: dict[str, str] = {}       # uid der Gruppe -> Name
    gruppen_mitglieder: dict[str, list[str]] = {}  # uid der Gruppe -> Mitglieder-UIDs
    kontakte_vcards = []

    for vcard in komponenten:
        if _ist_gruppe(vcard):
            uid = vcard.uid.value if hasattr(vcard, "uid") else vcard.fn.value
            gruppen_namen[uid] = vcard.fn.value
            gruppen_mitglieder[uid] = _gruppen_mitglieder_uids(vcard)
        else:
            kontakte_vcards.append(vcard)

    # Mitglied-UID -> Liste von Gruppen-UIDs, denen das Mitglied angehoert
    mitglied_zu_gruppen_uids: dict[str, list[str]] = {}
    for gruppen_uid, mitglieder in gruppen_mitglieder.items():
        for m_uid in mitglieder:
            mitglied_zu_gruppen_uids.setdefault(m_uid, []).append(gruppen_uid)

    ergebnis = []
    for vcard in kontakte_vcards:
        kontakt = _parse_kontakt(vcard)
        uid = vcard.uid.value if hasattr(vcard, "uid") else None
        gruppen_uids_fuer_kontakt = mitglied_zu_gruppen_uids.get(uid, []) if uid else []
        kontakt["gruppen"] = [gruppen_namen[g_uid] for g_uid in gruppen_uids_fuer_kontakt]
        kontakt["gruppen_uids"] = {gruppen_namen[g_uid]: g_uid for g_uid in gruppen_uids_fuer_kontakt}
        ergebnis.append(kontakt)
    return ergebnis


def _normalisiere_telefon(nummer: str) -> str:
    ziffern = re.sub(r"\D", "", nummer)
    return ziffern[-9:] if len(ziffern) >= 9 else ziffern


def finde_match(conn: sqlite3.Connection, kontakt: dict) -> int | None:
    """Einfache Dedup-Heuristik: exakte E-Mail- oder Telefon-Uebereinstimmung,
    sonst Vor-/Nachname exakt (case-insensitive). Gibt kontakt_id zurueck oder None."""
    for mail in kontakt.get("emails", []):
        row = conn.execute(
            "SELECT kontakt_id FROM emails WHERE lower(email) = lower(?) LIMIT 1",
            (mail["email"],),
        ).fetchone()
        if row:
            return row["kontakt_id"]

    eingehende_nummern = {_normalisiere_telefon(t["nummer"]) for t in kontakt.get("telefonnummern", [])}
    if eingehende_nummern:
        for row in conn.execute("SELECT kontakt_id, nummer FROM telefonnummern"):
            if _normalisiere_telefon(row["nummer"]) in eingehende_nummern:
                return row["kontakt_id"]

    if kontakt.get("vorname") and kontakt.get("nachname"):
        row = conn.execute(
            "SELECT id FROM kontakte WHERE lower(vorname) = lower(?) AND lower(nachname) = lower(?) LIMIT 1",
            (kontakt["vorname"], kontakt["nachname"]),
        ).fetchone()
        if row:
            return row["id"]

    return None


def _finde_match_fuer_import(conn: sqlite3.Connection, kontakt: dict) -> int | None:
    """Matching NUR fuer den automatischen, unbeaufsichtigten Kontakte.app-Import
    (importiere() unten) - bewusst strenger als das allgemeine finde_match() oben,
    das von der manuellen Kontakt-Neuanlage und den Mail-Vorschlaegen genutzt wird
    und dort VOR einem Zusammenfuehren immer eine sichtbare Rueckfrage zeigt.
    Regression (Nutzer-Meldung): zwei verschiedene echte Personen mit gemeinsamem
    Festnetzanschluss (z.B. Ehepaar am selben Wohnsitz) wurden ueber den
    Telefon-Abgleich in finde_match() faelschlich als derselbe Kontakt erkannt und
    ohne Rueckfrage zusammengefuehrt (Name der einen Person landete auf dem
    Kontakt-Datensatz mit der E-Mail der anderen). Reihenfolge hier bewusst nur:
    1) exakte Apple-UID (vCard-UID, stabil ueber wiederholte Importe desselben
       Adressbuchs hinweg - der einzige wirklich zuverlaessige Wiedererkennungs-
       Anker), 2) exakte E-Mail (eine persoenliche Mailadresse gehoert praktisch
       nie zwei verschiedenen Personen). Telefonnummer und blosser Namensabgleich
       werden hier NIE als alleiniges Kriterium verwendet."""
    apple_uid = kontakt.get("apple_uid")
    if apple_uid:
        row = conn.execute("SELECT id FROM kontakte WHERE apple_uid = ? LIMIT 1", (apple_uid,)).fetchone()
        if row:
            return row["id"]

    for mail in kontakt.get("emails", []):
        row = conn.execute(
            "SELECT kontakt_id FROM emails WHERE lower(email) = lower(?) LIMIT 1",
            (mail["email"],),
        ).fetchone()
        if row:
            return row["kontakt_id"]

    return None


def importiere(conn: sqlite3.Connection, inhalt: str, gruppen_als_ordner: bool = True) -> list[int]:
    """Parst eine .vcf-Datei und legt jeden Kontakt direkt an bzw. mergt ihn in einen
    erkannten bestehenden Kontakt (keine Review-Queue mehr, siehe docs/konzept.md
    Eintrag 2026-07-14: Korrekturen erfolgen danach direkt am Kontakt). Der Vorschlag
    (vorschlaege-Tabelle) wird intern weiterhin angelegt und sofort bestaetigt - die
    bestehende, nie ueberschreibende Merge-Logik (queries.merge_kontakt) bleibt so
    unveraendert die Quelle der Wahrheit dafuer, wie Import-Daten mit bestehenden
    Kontakten zusammengefuehrt werden. Gibt die Liste der betroffenen kontakt_id zurueck."""
    kontakte = parse_vcf(inhalt)
    kontakt_ids = []
    for kontakt in kontakte:
        gruppen = kontakt.pop("gruppen", [])
        gruppen_uids = kontakt.pop("gruppen_uids", {})
        kontakt_id = _finde_match_fuer_import(conn, kontakt)
        if gruppen_als_ordner and gruppen:
            kontakt["gruppen_als_ordner"] = gruppen
            kontakt["gruppen_apple_uids"] = gruppen_uids
        vorschlag_id = queries.create_vorschlag(conn, kontakt, kontakt_id=kontakt_id, quelle="import")
        kontakt_ids.append(queries.bestaetige_vorschlag(conn, vorschlag_id))
    return kontakt_ids
