"""Phase 3: Export einer Kontaktliste (eines Ordners) als CSV, PDF und/oder vCard.
Nimmt ueberall die bereits angereicherten Kontakt-Dicts aus db.queries.list_kontakte()
entgegen (inkl. telefonnummern/emails/adressen/urls)."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from sync.radicale import kontakt_zu_vcard

CSV_SPALTEN = [
    "Vorname", "Nachname", "Firma", "Rolle", "Kategorie",
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


def kontakte_csv(kontakte: list[dict]) -> bytes:
    """Erzeugt eine Excel-kompatible CSV (UTF-8 mit BOM, Semikolon als Trennzeichen -
    Standard-Spracheinstellung Excel DE verwendet Komma als Dezimaltrennzeichen und
    interpretiert Kommas in CSV sonst falsch)."""
    puffer = io.StringIO()
    writer = csv.writer(puffer, delimiter=";")
    writer.writerow(CSV_SPALTEN)
    for k in kontakte:
        writer.writerow([
            k.get("vorname", ""), k.get("nachname", ""), k.get("firma", ""),
            k.get("rolle", ""), k.get("kategorie", ""),
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

    for k in kontakte:
        name = f"{k.get('vorname', '')} {k.get('nachname', '')}".strip() or "(ohne Name)"
        zeilen = [Paragraph(escape(name), _STIL_NAME)]

        untertitel = " – ".join(t for t in (k.get("firma", ""), k.get("rolle", "")) if t)
        if untertitel:
            zeilen.append(Paragraph(escape(untertitel), _STIL_DETAIL))

        for label, text in (
            ("Telefon", _telefon_text(k)), ("E-Mail", _email_text(k)),
            ("Adresse", _adresse_text(k)), ("Web", _url_text(k)),
        ):
            if text:
                zeilen.append(Paragraph(f"<b>{label}:</b> {escape(text)}", _STIL_DETAIL))

        if k.get("notizen"):
            zeilen.append(Paragraph(f"<b>Notizen:</b> {escape(k['notizen'])}", _STIL_DETAIL))

        elemente.append(KeepTogether(zeilen))
        elemente.append(Spacer(1, 4 * mm))

    if not kontakte:
        elemente.append(Paragraph("Dieser Ordner enthält keine Kontakte.", _STIL_DETAIL))

    doc.build(elemente)
    return puffer.getvalue()
