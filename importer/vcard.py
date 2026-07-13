"""vCard-Import (Phase 0): parst .vcf-Exporte aus Kontakte.app und mappt sie
auf das Rubrica-Datenmodell. Erzeugt niemals direkt Kontakte - siehe web/imports.py
und db/queries.create_vorschlag."""
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
_TELEFON_TYP_MAPPING = {
    "work": "Direkt", "arbeit": "Direkt", "office": "Direkt", "main": "Allgemein",
    "allgemein": "Allgemein", "home": "Privat", "privat": "Privat", "private": "Privat",
    "cell": "Privat", "mobil": "Privat", "iphone": "Privat",
}
_EMAIL_TYP_MAPPING = {
    "work": "Direkt", "arbeit": "Direkt", "internet": "Direkt", "main": "Allgemein",
    "allgemein": "Allgemein", "home": "Privat", "privat": "Privat", "private": "Privat",
}


def _telefon_typ_normalisieren(rohtyp: str) -> str:
    return _TELEFON_TYP_MAPPING.get(rohtyp.lower(), "Direkt")


def _email_typ_normalisieren(rohtyp: str) -> str:
    return _EMAIL_TYP_MAPPING.get(rohtyp.lower(), "Direkt")


def _parse_kontakt(vcard) -> dict:
    vorname, nachname = _parse_name(vcard)
    firma = vcard.org.value[0] if hasattr(vcard, "org") and vcard.org.value else ""
    rolle = vcard.title.value if hasattr(vcard, "title") else ""

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
            "typ": _typ_von(adr) or "arbeit",
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
    'gruppen' (Namen der Apple-Gruppen, denen der Kontakt angehoert)."""
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

    # UID -> Liste von Gruppennamen, der das Mitglied angehoert
    mitglied_zu_gruppen: dict[str, list[str]] = {}
    for gruppen_uid, mitglieder in gruppen_mitglieder.items():
        for m_uid in mitglieder:
            mitglied_zu_gruppen.setdefault(m_uid, []).append(gruppen_namen[gruppen_uid])

    ergebnis = []
    for vcard in kontakte_vcards:
        kontakt = _parse_kontakt(vcard)
        uid = vcard.uid.value if hasattr(vcard, "uid") else None
        kontakt["gruppen"] = mitglied_zu_gruppen.get(uid, []) if uid else []
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


def importiere(conn: sqlite3.Connection, inhalt: str, gruppen_als_ordner: bool) -> int:
    """Parst eine .vcf-Datei und legt fuer jeden Kontakt einen Vorschlag an.
    Gibt die Anzahl erzeugter Vorschlaege zurueck. Aendert nie direkt kontakte."""
    kontakte = parse_vcf(inhalt)
    anzahl = 0
    for kontakt in kontakte:
        gruppen = kontakt.pop("gruppen", [])
        kontakt_id = finde_match(conn, kontakt)
        if gruppen_als_ordner and gruppen:
            kontakt["gruppen_als_ordner"] = gruppen
        queries.create_vorschlag(conn, kontakt, kontakt_id=kontakt_id, quelle="import")
        anzahl += 1
    return anzahl
