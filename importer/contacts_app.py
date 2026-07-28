"""Liest Kontakte + Gruppen direkt aus Kontakte.app (AppleScript) und importiert
sie in Rubrica. Gemeinsam genutzt vom CLI-Skript scripts/import_from_contacts_app.py
(bestehende Installationen, manuell) und vom Setup-Assistenten (web/setup.py,
Schritt 5 - neue Installationen). Siehe docs/konzept.md Abschnitt 5.6.

Datenschutz: Es werden keine Zwischendateien mit echten Kontaktdaten geschrieben,
und es wird nie ein vollstaendiger Datensatz ausgegeben - nur zusammenfassende Zahlen.
Die AppleScript-Ausgabe wird direkt von Python eingelesen und in die Rubrica-DB
geschrieben.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess

from importer.vcard import importiere

# Steuerzeichen statt NUL-Byte als Trenner - argv/subprocess erlauben keine
# eingebetteten Null-Bytes. ASCII-Trennzeichen (RS/GS/FS/US) kommen in vCard-Text
# praktisch nie vor.
PERSON_SEP = "\x1e"       # Record Separator
GROUPS_START = "\x1c"     # File Separator
GROUP_END = "\x1e"        # Record Separator
IDS_SEP = "\x1f"          # Unit Separator
MEMBER_SEP = "\x1d"       # Group Separator

APPLESCRIPT = f'''
tell application "Contacts"
    set vcardList to vcard of every person
    set AppleScript's text item delimiters to "{PERSON_SEP}"
    set vcardBlob to vcardList as text
    set AppleScript's text item delimiters to ""

    set groupBlob to ""
    repeat with g in every group
        set gName to name of g
        set memberIds to id of every person of g
        set AppleScript's text item delimiters to "{MEMBER_SEP}"
        set idsText to memberIds as text
        set AppleScript's text item delimiters to ""
        set groupBlob to groupBlob & gName & "{IDS_SEP}" & idsText & "{GROUP_END}"
    end repeat

    return vcardBlob & "{GROUPS_START}" & groupBlob
end tell
'''


def _hole_daten() -> tuple[list[str], dict[str, list[str]]]:
    # AppleScripts "vcard of every person" ist bei grossen, echten Adressbuechern
    # (mehrere Tausend Kontakte) sehr langsam - im Setup-Assistenten (anders als
    # beim urspruenglichen manuellen Dev-Skript) sieht ein unbeaufsichtigter
    # Erstnutzer das, daher grosszuegiger Timeout statt der frueheren 180s.
    ergebnis = subprocess.run(
        ["osascript", "-e", APPLESCRIPT],
        capture_output=True, text=True, check=True, timeout=600,
    )
    personen_teil, gruppen_teil = ergebnis.stdout.split(GROUPS_START, 1)
    vcards = personen_teil.split(PERSON_SEP)

    gruppen: dict[str, list[str]] = {}
    for eintrag in gruppen_teil.split(GROUP_END):
        eintrag = eintrag.strip()
        if not eintrag:
            continue
        name, ids_text = eintrag.split(IDS_SEP, 1)
        ids = [i for i in ids_text.split(MEMBER_SEP) if i]
        gruppen[name] = ids
    return vcards, gruppen


# Erlaubt auch Apple's gruppierte Properties wie "item2.X-ABADR:ch" (Punkt vor
# dem eigentlichen Property-Namen) - wurden zuvor faelschlich als verwaiste
# Fortsetzungszeile erkannt und an die vorherige Zeile angehaengt (Bug, siehe
# docs/konzept.md).
_GUELTIGE_ZEILE = re.compile(r"^[A-Za-z0-9_.-]+[;:]")


def _repariere_zeilenumbrueche(vcard_text: str) -> str:
    """Manche Adressen in Kontakte.app enthalten unescapte Zeilenumbrueche
    (z.B. mehrzeilige Strassenfelder), die die vCard-Zeilenfaltung verletzen -
    ohne fuehrendes Leerzeichen ist das keine gueltige RFC-6350-Fortsetzung.
    Haengt solche verwaisten Zeilen wieder an die vorherige Zeile an."""
    repariert: list = []
    for zeile in vcard_text.splitlines():
        if zeile.startswith((" ", "\t")) or _GUELTIGE_ZEILE.match(zeile) or not zeile.strip():
            repariert.append(zeile)
        elif repariert:
            repariert[-1] = repariert[-1] + " " + zeile.strip()
        else:
            repariert.append(zeile)
    return "\n".join(repariert)


def _x_abuid(vcard_text: str):
    match = re.search(r"^X-ABUID:(.+)$", vcard_text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _mit_uid(vcard_text: str, uid: str) -> str:
    zeilen = _repariere_zeilenumbrueche(vcard_text.strip()).splitlines()
    return "\r\n".join([zeilen[0], f"UID:{uid}"] + zeilen[1:]) + "\r\n"


def _gruppen_vcard(name: str, mitglieder_uids: list) -> str:
    zeilen = ["BEGIN:VCARD", "VERSION:3.0", f"UID:gruppe-{name}", f"FN:{name}",
              "X-ADDRESSBOOKSERVER-KIND:group"]
    for uid in mitglieder_uids:
        zeilen.append(f"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:{uid}")
    zeilen.append("END:VCARD")
    return "\r\n".join(zeilen) + "\r\n"


def importiere_aus_kontakte_app(conn: sqlite3.Connection) -> dict:
    """Liest den kompletten Bestand aus Kontakte.app und importiert ihn nach
    Rubrica (nie destruktiv, siehe importer.vcard.importiere / queries.merge_kontakt).
    Gibt eine Zusammenfassung zurueck, wirft bei AppleScript-Fehlern (z.B. Zugriff
    auf Kontakte.app verweigert) die zugrundeliegende Exception weiter."""
    vcards, gruppen = _hole_daten()

    vcf_teile = []
    ohne_uid = 0
    for vc in vcards:
        vc = vc.strip()
        if not vc:
            continue
        uid = _x_abuid(vc)
        if uid:
            vcf_teile.append(_mit_uid(vc, uid))
        else:
            ohne_uid += 1
            vcf_teile.append(_repariere_zeilenumbrueche(vc) + "\r\n")

    # Alle Gruppen-vCards als gemeinsamer Block: der Parser (importer/vcard.py)
    # erkennt Gruppenzugehoerigkeit nur, wenn Person- und Gruppen-vCards im selben
    # Aufruf vorkommen. Da jede Person einzeln importiert wird (Fehlerisolation),
    # werden die Gruppen-vCards jedem einzelnen Aufruf angehaengt.
    gruppen_block = "\n".join(
        _gruppen_vcard(name, mitglieder) for name, mitglieder in gruppen.items() if mitglieder
    )

    anzahl = 0
    fehler = 0
    # Jede vCard einzeln importieren statt als ein grosser Block: eine einzelne
    # fehlerhafte/legacy-kodierte vCard (z.B. alte Quoted-Printable-Kodierung)
    # soll nicht den gesamten Import abbrechen.
    for vc in vcf_teile:
        try:
            anzahl += len(importiere(conn, vc + "\n" + gruppen_block, gruppen_als_ordner=True))
        except Exception:
            fehler += 1

    anzahl_kontakte = conn.execute("SELECT COUNT(*) FROM kontakte").fetchone()[0]
    anzahl_ordner = conn.execute("SELECT COUNT(*) FROM projekte").fetchone()[0]

    return {
        "gefunden": len(vcards),
        "gruppen_gefunden": len(gruppen),
        "importiert": anzahl,
        "fehler": fehler,
        "ohne_uid": ohne_uid,
        "kontakte_gesamt": anzahl_kontakte,
        "ordner_gesamt": anzahl_ordner,
    }
