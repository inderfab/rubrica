"""Phase 3: Export einer Kontaktliste (eines Ordners) als CSV, PDF und/oder vCard.
Nimmt ueberall die bereits angereicherten Kontakt-Dicts aus db.queries.list_kontakte()
entgegen (inkl. telefonnummern/emails/adressen/urls)."""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from sync.radicale import kontakt_zu_vcard

CSV_SPALTEN = [
    "Vorname", "Nachname", "Firma", "Funktion", "Rolle",
    "Telefon", "E-Mail", "Adresse", "Homepage", "Notizen",
]


def _telefon_text(kontakt: dict) -> str:
    return "; ".join(f"{t['typ']}: {t['nummer']}" for t in kontakt.get("telefonnummern", []))


def _email_text(kontakt: dict) -> str:
    return "; ".join(f"{e['typ']}: {e['email']}" for e in kontakt.get("emails", []))


def _adresse_text(kontakt: dict) -> str:
    zeilen = []
    for a in kontakt.get("adressen", []):
        teile = [a.get("strasse", ""), f"{a.get('plz', '')} {a.get('ort', '')}".strip()]
        teile = [t for t in teile if t]
        if a.get("land"):
            teile.append(a["land"])
        if teile:
            zeilen.append(f"{a.get('typ', '')}: {', '.join(teile)}")
    return "; ".join(zeilen)


def _url_text(kontakt: dict) -> str:
    return "; ".join(u["url"] for u in kontakt.get("urls", []))


def _bkp_sortier_schluessel(kategorie: str) -> tuple:
    """Sortiert BKP-klassifizierte Funktionen ("297.0 Geometer") numerisch nach
    Nummer statt alphabetisch (sonst wuerde z.B. "299" vor "297" einsortiert).
    Eintraege ohne fuehrende BKP-Nummer (z.B. "Bauherrschaft/Kundschaft") kommen
    zuerst, alphabetisch - passt zur Adressliste-Konvention, in der die
    Bauherrschaft ohne BKP-Nummer erscheint."""
    treffer = re.match(r"^(\d+)(?:\.(\d+))?\s", kategorie.strip() + " ")
    if not treffer:
        return (0, 0, 0, kategorie)
    return (1, int(treffer.group(1)), int(treffer.group(2) or 0), kategorie)


def _sortiere_fuer_export(kontakte: list[dict]) -> list[dict]:
    """Sortiert Kontakte fuer den Export nach Funktion (BKP-Nummer aufsteigend),
    innerhalb derselben Funktion nach Firma - Personen derselben Firma landen
    dadurch direkt nebeneinander."""
    return sorted(
        kontakte,
        key=lambda k: (_bkp_sortier_schluessel(k.get("kategorie", "")), k.get("firma", ""), k.get("nachname", "")),
    )


def _gruppiere_fuer_export(kontakte: list[dict]) -> list[dict]:
    """Gruppiert Kontakte fuer den PDF-Export: zuerst nach Funktion (BKP-Nummer
    aufsteigend sortiert), innerhalb einer Funktion nach Firma - mehrere Personen
    derselben Firma erscheinen dann als ein gemeinsamer Firmenblock (Firmenname/
    -adresse nur einmal), analog zur vom Nutzer bereitgestellten Beispiel-
    Adressliste (Firma einmal oben, mehrere Sachbearbeiter darunter)."""
    sortiert = _sortiere_fuer_export(kontakte)

    gruppen: list[dict] = []
    for k in sortiert:
        funktion = k.get("kategorie", "")
        firma = k.get("firma", "")
        if (gruppen and gruppen[-1]["funktion"] == funktion
                and gruppen[-1]["firmen"] and gruppen[-1]["firmen"][-1]["firma"] == firma):
            gruppen[-1]["firmen"][-1]["kontakte"].append(k)
        elif gruppen and gruppen[-1]["funktion"] == funktion:
            gruppen[-1]["firmen"].append({"firma": firma, "kontakte": [k]})
        else:
            gruppen.append({"funktion": funktion, "firmen": [{"firma": firma, "kontakte": [k]}]})
    return gruppen


def kontakte_csv(kontakte: list[dict]) -> bytes:
    """Erzeugt eine Excel-kompatible CSV (UTF-8 mit BOM, Semikolon als Trennzeichen -
    Standard-Spracheinstellung Excel DE verwendet Komma als Dezimaltrennzeichen und
    interpretiert Kommas in CSV sonst falsch). Zeilen sortiert wie der PDF-Export
    (nach Funktion/BKP-Nummer, dann Firma), fuer eine konsistente Reihenfolge in
    beiden Formaten."""
    puffer = io.StringIO()
    writer = csv.writer(puffer, delimiter=";")
    writer.writerow(CSV_SPALTEN)
    for k in _sortiere_fuer_export(kontakte):
        writer.writerow([
            k.get("vorname", ""), k.get("nachname", ""), k.get("firma", ""),
            k.get("kategorie", ""), k.get("rolle", ""),
            _telefon_text(k), _email_text(k), _adresse_text(k), _url_text(k),
            k.get("notizen", ""),
        ])
    return puffer.getvalue().encode("utf-8-sig")


def kontakte_vcard(kontakte: list[dict]) -> bytes:
    """Eine einzelne .vcf-Datei mit allen Kontakten (Mehrfach-vCard) - direkt per
    Doppelklick in Kontakte.app importierbar."""
    return "".join(kontakt_zu_vcard(k) for k in kontakte).encode("utf-8")


_STYLES = getSampleStyleSheet()
_STIL_NAME = ParagraphStyle("KontaktName", parent=_STYLES["Heading4"], spaceAfter=1 * mm)
_STIL_DETAIL = ParagraphStyle("KontaktDetail", parent=_STYLES["Normal"], fontSize=9, leading=12)
_STIL_FUNKTION = ParagraphStyle(
    "FunktionGruppe", parent=_STYLES["Heading3"],
    textColor=colors.white, backColor=colors.HexColor("#2f3437"),
    spaceBefore=4 * mm, spaceAfter=2 * mm, leftIndent=2 * mm, borderPadding=2,
)
_STIL_FIRMA = ParagraphStyle("Firma", parent=_STYLES["Heading4"], spaceAfter=0.5 * mm)


def kontakte_pdf(ordner_name: str, kontakte: list[dict]) -> bytes:
    puffer = io.BytesIO()
    doc = SimpleDocTemplate(
        puffer, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
        title=f"Rubrica – {ordner_name}",
    )
    elemente = []

    kopf_tabelle = Table(
        [[Paragraph(f"<b>{escape(ordner_name)}</b>", _STYLES["Title"])]],
        colWidths=[doc.width],
    )
    elemente.append(kopf_tabelle)
    elemente.append(Paragraph(
        f"Rubrica – Kontaktliste – {len(kontakte)} Kontakt(e) – "
        f"erzeugt am {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        ParagraphStyle("Unter", parent=_STYLES["Normal"], textColor=colors.grey, spaceAfter=6 * mm),
    ))

    # Gruppiert nach Funktion (BKP-Nummer aufsteigend) und innerhalb einer Funktion
    # nach Firma - mehrere Personen derselben Firma erscheinen als ein
    # gemeinsamer Firmenblock (Firmenname/-adresse nur einmal), statt wie zuvor
    # jede Person unabhaengig und unsortiert aufzulisten (Nutzer-Vorlage).
    for gruppe in _gruppiere_fuer_export(kontakte):
        if gruppe["funktion"]:
            elemente.append(Paragraph(escape(gruppe["funktion"]), _STIL_FUNKTION))

        for firmen_gruppe in gruppe["firmen"]:
            firma = firmen_gruppe["firma"]
            firma_kontakte = firmen_gruppe["kontakte"]
            block = []

            if firma:
                block.append(Paragraph(escape(firma), _STIL_FIRMA))
                firmen_adresse = next((_adresse_text(k) for k in firma_kontakte if _adresse_text(k)), "")
                if firmen_adresse:
                    block.append(Paragraph(escape(firmen_adresse), _STIL_DETAIL))

            for k in firma_kontakte:
                name = f"{k.get('vorname', '')} {k.get('nachname', '')}".strip() or "(ohne Name)"
                zeile_stil = _STIL_DETAIL if firma else _STIL_NAME
                block.append(Paragraph(f"<b>{escape(name)}</b>" if firma else escape(name), zeile_stil))

                if k.get("rolle"):
                    block.append(Paragraph(escape(k["rolle"]), _STIL_DETAIL))
                elif not firma and gruppe["funktion"]:
                    block.append(Paragraph(escape(gruppe["funktion"]), _STIL_DETAIL))

                for label, text in (("Telefon", _telefon_text(k)), ("E-Mail", _email_text(k)), ("Web", _url_text(k))):
                    if text:
                        block.append(Paragraph(f"<b>{label}:</b> {escape(text)}", _STIL_DETAIL))

                if not firma:
                    adresse = _adresse_text(k)
                    if adresse:
                        block.append(Paragraph(f"<b>Adresse:</b> {escape(adresse)}", _STIL_DETAIL))

                if k.get("notizen"):
                    block.append(Paragraph(f"<b>Notizen:</b> {escape(k['notizen'])}", _STIL_DETAIL))
                block.append(Spacer(1, 2 * mm))

            elemente.append(KeepTogether(block))
            elemente.append(Spacer(1, 3 * mm))

    if not kontakte:
        elemente.append(Paragraph("Dieser Ordner enthält keine Kontakte.", _STIL_DETAIL))

    doc.build(elemente)
    return puffer.getvalue()
