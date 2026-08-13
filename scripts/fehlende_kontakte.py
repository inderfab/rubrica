"""Vergleicht einen Ordner mit alten .vcf-Dateien gegen den Rubrica-Bestand und
schreibt jeden dort fehlenden Kontakt als einzelne .vcf-Datei heraus.

Anlass (Nutzer-Meldung): Kontakte, die sich eine allgemeine Telefonnummer oder
E-Mail teilen, wurden zusammengefuehrt - von zwei Personen derselben Firma blieb
eine uebrig, die andere fehlte seither. Genau solche Faelle findet dieses Skript:
verglichen wird ueber den NAMEN, nicht ueber E-Mail oder Telefon. Die Kontaktdaten
eines zusammengefuehrten Kontakts stehen ja weiterhin in der Datenbank - nur eben
beim falschen Menschen.

Aufruf:

    .venv/bin/python scripts/fehlende_kontakte.py <vcf-ordner> <rubrica.db> [ziel-ordner]

Schreibt nichts in die Datenbank und veraendert die Quelldateien nicht.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vobject  # noqa: E402

_KARTE = re.compile(r"BEGIN:VCARD.*?END:VCARD", re.DOTALL | re.IGNORECASE)


def _schluessel(text: str) -> str:
    """Vergleichsform eines Namens: ohne Akzente, ohne Mehrfach-Leerzeichen,
    kleingeschrieben. "von Arx" und "Von  Arx" sind damit derselbe Mensch."""
    ohne_akzente = "".join(
        z for z in unicodedata.normalize("NFD", text or "")
        if unicodedata.category(z) != "Mn"
    )
    return " ".join(ohne_akzente.lower().split())


def _namensschluessel(vorname: str, nachname: str, firma: str) -> str:
    name = _schluessel(f"{vorname} {nachname}")
    # Karten ohne Personennamen (reine Firmeneintraege) ueber die Firma vergleichen.
    return name or f"firma:{_schluessel(firma)}"


def _karten_aus_ordner(ordner: Path) -> list:
    """(Rohtext, geparster Kontakt) je Karte. Der Rohtext wird mitgefuehrt, damit
    die herausgeschriebene Datei exakt der urspruenglichen Karte entspricht -
    einschliesslich Feldern, die Rubrica selbst nicht liest."""
    from importer.vcard import _parse_kontakt

    karten = []
    for datei in sorted(ordner.glob("*.vcf")):
        text = datei.read_text(encoding="utf-8", errors="replace")
        for treffer in _KARTE.finditer(text):
            roh = treffer.group(0)
            try:
                vcard = vobject.readOne(roh)
            except Exception:
                continue
            if getattr(vcard, "contents", {}).get("x-addressbookserver-kind"):
                continue  # Gruppen-Karte, kein Kontakt
            try:
                karten.append((roh, _parse_kontakt(vcard)))
            except Exception:
                continue
    return karten


def _bestand(db_pfad: Path) -> tuple:
    """(Namensschluessel im Bestand, E-Mail -> Name, Telefonziffern -> Name)."""
    conn = sqlite3.connect(f"file:{db_pfad}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        namen = set()
        for r in conn.execute("SELECT vorname, nachname, firma FROM kontakte"):
            namen.add(_namensschluessel(r["vorname"], r["nachname"], r["firma"]))

        mails, telefone = {}, {}
        for r in conn.execute(
            "SELECT e.email AS wert, k.vorname, k.nachname, k.firma FROM emails e "
            "JOIN kontakte k ON k.id = e.kontakt_id"
        ):
            mails.setdefault(r["wert"].strip().lower(),
                             f"{r['vorname']} {r['nachname']} {r['firma']}".strip())
        for r in conn.execute(
            "SELECT t.nummer AS wert, k.vorname, k.nachname, k.firma FROM telefonnummern t "
            "JOIN kontakte k ON k.id = t.kontakt_id"
        ):
            telefone.setdefault(re.sub(r"\D", "", r["wert"] or ""),
                                f"{r['vorname']} {r['nachname']} {r['firma']}".strip())
        return namen, mails, telefone
    finally:
        conn.close()


def _dateiname(kontakt: dict, belegt: set) -> str:
    roh = f"{kontakt.get('nachname', '')} {kontakt.get('vorname', '')}".strip() \
        or kontakt.get("firma", "") or "Ohne Namen"
    sauber = re.sub(r"[^\w\- ]", "", roh, flags=re.UNICODE).strip() or "Kontakt"
    name, n = sauber, 1
    while f"{name}.vcf" in belegt:
        n += 1
        name = f"{sauber} ({n})"
    belegt.add(f"{name}.vcf")
    return f"{name}.vcf"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    quelle = Path(sys.argv[1]).expanduser()
    db_pfad = Path(sys.argv[2]).expanduser()
    ziel = Path(sys.argv[3]).expanduser() if len(sys.argv) > 3 else \
        quelle.parent / "Fehlende Kontakte"

    karten = _karten_aus_ordner(quelle)
    namen, mails, telefone = _bestand(db_pfad)
    print(f"{len(karten)} Karten in {quelle.name}, {len(namen)} Namen in der Datenbank")

    ziel.mkdir(parents=True, exist_ok=True)
    belegt: set = set()
    gesehen: set = set()
    fehlend = []

    for roh, kontakt in karten:
        schluessel = _namensschluessel(kontakt.get("vorname", ""), kontakt.get("nachname", ""),
                                        kontakt.get("firma", ""))
        if not schluessel or schluessel in namen or schluessel in gesehen:
            continue
        gesehen.add(schluessel)

        # Wo stecken die Daten jetzt? Bei einer Zusammenfuehrung findet sich die
        # E-Mail oder Telefonnummer der fehlenden Person unter einem anderen Namen -
        # das ist der Beleg dafuer, dass sie nicht einfach nie importiert wurde.
        spur = ""
        for mail in kontakt.get("emails", []):
            treffer = mails.get((mail.get("email") or "").strip().lower())
            if treffer:
                spur = f"E-Mail {mail['email']} steht jetzt bei: {treffer}"
                break
        if not spur:
            for tel in kontakt.get("telefonnummern", []):
                treffer = telefone.get(re.sub(r"\D", "", tel.get("nummer") or ""))
                if treffer:
                    spur = f"Telefon {tel['nummer']} steht jetzt bei: {treffer}"
                    break

        datei = _dateiname(kontakt, belegt)
        (ziel / datei).write_text(roh.strip() + "\r\n", encoding="utf-8")
        fehlend.append((datei, kontakt, spur))

    zeilen = [
        f"Fehlende Kontakte: {len(fehlend)}",
        f"Verglichen: {quelle}",
        f"Gegen: {db_pfad}",
        "",
        "Verglichen wird ueber den Namen. Steht daneben ein Hinweis, wo die E-Mail",
        "oder Telefonnummer heute zu finden ist, wurde der Kontakt beim Import mit",
        "einem anderen zusammengefuehrt - die Daten sind also da, der Mensch fehlt.",
        "",
    ]
    for datei, kontakt, spur in sorted(fehlend, key=lambda e: e[0].lower()):
        beschreibung = f"{kontakt.get('vorname', '')} {kontakt.get('nachname', '')}".strip()
        if kontakt.get("firma"):
            beschreibung += f" ({kontakt['firma']})"
        zeilen.append(f"- {beschreibung or datei}")
        if spur:
            zeilen.append(f"    {spur}")
    (ziel / "_Uebersicht.txt").write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    zusammengefuehrt = sum(1 for _, _, spur in fehlend if spur)
    print(f"{len(fehlend)} fehlende Kontakte nach {ziel} geschrieben")
    print(f"davon {zusammengefuehrt} nachweislich in einen anderen Kontakt zusammengefuehrt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
