"""Parst eine hineinkopierte E-Mail-Signatur (Freitext) heuristisch in die Rubrica-
Kontaktfelder. Bewusst als *Vorbefuellung* gedacht - der Nutzer korrigiert danach.
Kein Anspruch auf Perfektion: lieber die sicheren Felder (E-Mail, Telefon, Web,
Firma, Adresse) zuverlaessig treffen als beim Namen zu raten.

Ausgabe-Dict ist kompatibel zu db.queries.create_kontakt() / importer.vcard.
"""
from __future__ import annotations

import re

# ── E-Mail ────────────────────────────────────────────────────────────────────
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# ── Web ───────────────────────────────────────────────────────────────────────
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>()]+", re.IGNORECASE)

# ── Telefon (Schweizer + internationale Formate) ─────────────────────────────
# Erlaubt +41.., 0041.., 0.. mit Leerzeichen/Punkt/Schraegstrich/Bindestrich als Trenner.
_TEL = re.compile(
    r"(?:\+41|0041|\+\d{1,3}|0)\s?\(?\d{1,3}\)?(?:[\s.\-/]?\d{2,4}){2,4}"
)

# ── Schweizer PLZ + Ort (4 Ziffern, dann Ortsname) ──────────────────────────
_PLZ_ORT = re.compile(r"\b(\d{4})\s+([A-Za-zÄÖÜäöüéèà\-. ]{2,40})$")
# Strasse: Wort(e) endend auf -strasse/-str./-weg/-gasse/-platz + Hausnummer, ODER
# generisch: Text + Hausnummer am Zeilenende.
_STRASSE = re.compile(r"^(.*?(?:str(?:asse|\.)|weg|gasse|platz|rain|halde|matt)\S*\.?\s+\d+\w?)\b",
                      re.IGNORECASE)
_STRASSE_GENERISCH = re.compile(r"^([A-Za-zÄÖÜäöü.\- ]{3,40}\s+\d{1,4}\s*\w?)$")

# ── Firma: Rechtsform-Kennungen (CH/DE/international) ─────────────────────────
_FIRMA_KENNUNG = re.compile(
    r"\b(AG|GmbH|SA|Sàrl|Sarl|SAGL|KG|OHG|e\.K\.|Ltd|Inc|LLC|"
    r"Architekt\w*|Ingenieur\w*|Planung\w*|Partner|Generalunternehm\w*)\b",
    re.IGNORECASE,
)

# ── Funktion/Rolle-Schluesselwoerter ─────────────────────────────────────────
_ROLLE_KENNUNG = re.compile(
    # "dipl\." separat: das abschliessende \b der Gruppe greift nie nach einem
    # Punkt (nicht-Wortzeichen), wenn danach ein Leerzeichen folgt - beide Seiten
    # sind dann Nicht-Wortzeichen, also keine Wortgrenze.
    r"\b(Geschäftsführer\w*|Inhaber\w*|Partner\w*|Projektleiter\w*|Bauleiter\w*|"
    r"Architekt\w*|Ingenieur\w*|Geolog\w*|Planer\w*|Sachbearbeiter\w*|"
    r"CEO|Leiter\w*|Vorsitzende\w*)\b|\bdipl\.",
    re.IGNORECASE,
)

# ── Zeilen, die sicher KEIN Name sind ────────────────────────────────────────
_KEIN_NAME = re.compile(
    r"@|www\.|https?://|\d|(?:str(?:asse|\.)|weg|gasse|platz)|"
    r"\b(AG|GmbH|SA|Tel|Fax|Mobile|Mob|Fon|E-?Mail|Mail|Web|Postfach|"
    r"CH|Postadresse|Direkt)\b",
    re.IGNORECASE,
)

# Gruss-/Schlussformeln, die wie ein Name aussehen koennen ("Freundliche Grüsse").
_GRUSSFORMEL = re.compile(
    r"grüsse|grüße|gruss|gruß|grüessli|regards|hochachtung|freundlich\w*|"
    r"gesendet von|sent from|beste\b|liebe\b|herzlich\w*",
    re.IGNORECASE,
)


def _telefon_typ(kontext: str) -> str:
    """Klassifiziert eine Nummer anhand des Textes davor (Label) bzw. der Vorwahl."""
    k = kontext.lower()
    if re.search(r"\bfax\b|\bf[:.]?\s*$", k):
        return "fax"
    if re.search(r"\bmob\w*|\bnatel|\bhandy|\bm[:.]?\s*$|\bcell", k):
        return "mobil"
    if re.search(r"\btel|\bfon|\bt[:.]?\s*$|\bdirekt|\bfestnetz|\bp[:.]?\s*$", k):
        return "arbeit"
    return ""


def _normalisiere_nummer(roh: str) -> str:
    nummer = re.sub(r"[^\d+]", " ", roh)
    return re.sub(r"\s+", " ", nummer).strip()


def _ist_plausible_telefonnummer(normalisiert: str) -> bool:
    """Grobe Plausibilitaetspruefung fuer Schweizer/internationale Nummern -
    verwirft Zahlenfolgen, die zufaellig wie eine Nummer aussehen (Copyright-
    Jahr + ID, Referenznummern etc. aus Newsletter-Fusszeilen o.ae.), aber
    keine echte Rufnummer sind. Schweizer Vorwahlen/Mobilvorwahlen beginnen nie
    mit einer 0 oder 1 als zweiter Ziffer (z.B. "011..." ist ungueltig)."""
    ziffern = re.sub(r"\D", "", normalisiert)
    if normalisiert.startswith("+41"):
        rest = ziffern[2:]  # "41..." -> Laendervorwahl abschneiden
        return len(rest) == 9 and rest[0] not in "01"
    if ziffern.startswith("0041"):
        rest = ziffern[4:]
        return len(rest) == 9 and rest[0] not in "01"
    if normalisiert.startswith("+"):
        # andere Laendervorwahl - grobe Plausibilitaet (Laenge), keine Detailpruefung.
        return 8 <= len(ziffern) <= 15
    if ziffern.startswith("0"):
        return len(ziffern) == 10 and ziffern[1] not in "01"
    return False


def parse_signatur(text: str) -> dict:
    """Nimmt Signatur-Freitext, gibt ein Kontakt-Dict zurueck (alle Felder optional)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    zeilen = [z.strip() for z in text.split("\n")]
    zeilen_nonempty = [z for z in zeilen if z]

    emails, urls, telefonnummern = [], [], []
    gesehene_mails, gesehene_nummern, gesehene_urls = set(), set(), set()

    for zeile in zeilen:
        for m in _EMAIL.finditer(zeile):
            adr = m.group(0).strip(".,;:")
            if adr.lower() not in gesehene_mails:
                gesehene_mails.add(adr.lower())
                emails.append({"typ": "arbeit", "email": adr})
        for m in _URL.finditer(zeile):
            u = m.group(0).strip(".,;:")
            # E-Mail-Domain nicht faelschlich als URL zaehlen
            if "@" in u:
                continue
            # Lange Tracking-/Freigabe-Links (SharePoint, OneDrive u.ae. mit
            # kodierten Query-Strings) nicht als "Homepage" uebernehmen - echte
            # Firmen-Homepages sind kurz, solche Links koennen mehrere hundert
            # Zeichen lang sein und wuerden das Formularfeld verunstalten.
            if len(u) > 120:
                continue
            if u.lower() not in gesehene_urls:
                gesehene_urls.add(u.lower())
                urls.append({"typ": "homepage", "url": u})
        for m in _TEL.finditer(zeile):
            roh = m.group(0)
            normalisiert = _normalisiere_nummer(roh)
            ziffern = re.sub(r"\D", "", normalisiert)
            if len(ziffern) < 9:  # zu kurz fuer eine echte Rufnummer
                continue
            if not _ist_plausible_telefonnummer(normalisiert):
                continue
            if normalisiert in gesehene_nummern:
                continue
            gesehene_nummern.add(normalisiert)
            kontext = zeile[:m.start()][-12:]
            typ = _telefon_typ(kontext)
            if not typ:
                typ = "mobil" if re.search(r"(?:\+41\s?|0)7\d", normalisiert) else "arbeit"
            telefonnummern.append({"typ": typ, "nummer": normalisiert})

    firma = ""
    rolle = ""
    for zeile in zeilen_nonempty:
        # Laengen-Obergrenze: eine echte Firmenzeile ist kurz. Verhindert, dass ganze
        # Absaetze (z.B. Newsletter-Fusszeilen, die zufaellig "AG" enthalten) als
        # Firma uebernommen werden.
        if (not firma and len(zeile) <= 80 and _FIRMA_KENNUNG.search(zeile)
                and "@" not in zeile and not _URL.search(zeile)):
            firma = zeile
        if not rolle and _ROLLE_KENNUNG.search(zeile) and _FIRMA_KENNUNG.search(zeile) is None:
            rolle = zeile

    # ── Adresse: Strassen-Zeile + PLZ/Ort-Zeile suchen ──────────────────────
    strasse = plz = ort = ""
    for zeile in zeilen_nonempty:
        if not strasse:
            m = _STRASSE.match(zeile) or _STRASSE_GENERISCH.match(zeile)
            if m and "@" not in zeile:
                strasse = m.group(1).strip()
        m2 = _PLZ_ORT.search(zeile)
        if m2 and not plz:
            plz, ort = m2.group(1), m2.group(2).strip()
    adressen = []
    if strasse or plz or ort:
        adressen.append({"typ": "arbeit", "strasse": strasse, "plz": plz,
                         "ort": ort, "region": "", "land": ""})

    # ── Name: erste Zeile, die wie ein Personenname aussieht ────────────────
    vorname = nachname = ""
    for zeile in zeilen_nonempty[:4]:
        if _KEIN_NAME.search(zeile) or _GRUSSFORMEL.search(zeile):
            continue
        if zeile == firma:
            continue
        # Eine Funktions-/Titelzeile ("Dipl. Ing. Arch.", "Gesamtprojektleiter HLKS")
        # ist kein Personenname, auch wenn sie oberflaechlich wie einer aussieht
        # (mehrere grossgeschriebene Woerter).
        if _ROLLE_KENNUNG.search(zeile):
            continue
        worte = zeile.split()
        if 2 <= len(worte) <= 4 and all(w[:1].isupper() for w in worte if w):
            vorname = " ".join(worte[:-1])
            nachname = worte[-1]
            break

    return {
        "vorname": vorname, "nachname": nachname, "firma": firma,
        "rolle": rolle, "kategorie": "", "notizen": "",
        "telefonnummern": telefonnummern, "emails": emails,
        "adressen": adressen, "urls": urls,
    }
