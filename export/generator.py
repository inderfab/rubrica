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
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from sync.radicale import kontakt_zu_vcard

CSV_SPALTEN = [
    "Vorname", "Nachname", "Firma", "Funktion", "Rolle",
    "Telefon", "E-Mail", "Adresse", "Homepage", "Notizen",
]


def _telefon_text(kontakt: dict) -> str:
    return "; ".join(f"{t['typ']}: {t['nummer']}" for t in kontakt.get("telefonnummern", []))


def _telefon_liste(kontakt: dict, mobil: bool) -> str:
    """Trennt Telefonnummern in Festnetz/Fax/Direktwahl vs. Mobil - im PDF-Export
    als eigene Spalten, analog zur Nutzer-Vorlage ("Telefon/Fax/Direktwahl" und
    "Mobil" getrennt)."""
    return "<br/>".join(
        escape(t["nummer"]) for t in kontakt.get("telefonnummern", [])
        if (t.get("typ") == "mobil") == mobil
    )


def _email_und_web_text(kontakt: dict) -> str:
    teile = [e["email"] for e in kontakt.get("emails", [])] + [u["url"] for u in kontakt.get("urls", [])]
    return "<br/>".join(escape(t) for t in teile)


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
_STIL_TITEL = ParagraphStyle("OrdnerTitel", parent=_STYLES["Title"], alignment=0, spaceAfter=1 * mm)
_STIL_UNTERTITEL = ParagraphStyle("Untertitel", parent=_STYLES["Normal"], textColor=colors.grey, spaceAfter=5 * mm)
_STIL_ZELLE = ParagraphStyle("Zelle", parent=_STYLES["Normal"], fontSize=8, leading=10)
_STIL_KOPFZELLE = ParagraphStyle(
    "Kopfzelle", parent=_STIL_ZELLE, fontName="Helvetica-Bold", textColor=colors.white,
)

_TABELLEN_SPALTEN = [
    "BKP Nummer", "Unternehmen", "Sachbearbeitung", "Funktion",
    "Telefon/Fax/Direktwahl", "Mobil", "E-Mail/Webseite",
]
_SPALTEN_ANTEILE = [0.13, 0.18, 0.14, 0.14, 0.15, 0.08, 0.18]


def _bkp_zellen_text(funktion: str) -> str:
    """Bricht "292 Bauingenieur/in" nach der Nummer um ("292<br/>Bauingenieur/in")
    statt die lange Bezeichnung mitten im Wort umbrechen zu lassen (reportlab
    trennt sonst harte Wortumbrueche, sobald ein Wort allein nicht in die enge
    BKP-Spalte passt)."""
    teile = funktion.split(" ", 1)
    return "<br/>".join(escape(t) for t in teile)


def _kopf_fuss_zeichner(firmenname: str, logo_pfad: str):
    """Wird pro Seite als Canvas-Callback aufgerufen (nicht als Flowable), damit
    Firmenname/Logo auf JEDER Seite oben erscheinen, nicht nur auf der ersten -
    Platypus-Flowables wiederholen sich sonst nicht automatisch ueber Seiten
    hinweg. Firmenname ist mittig oben, Logo rechts oben (Nutzer-Vorgabe;
    ersetzt den fixen "mmt"-Platzhalter aus der Beispielvorlage), beides ueber
    die Einstellungen konfigurierbar."""
    def zeichnen(canvas, doc):
        breite, hoehe = doc.pagesize
        canvas.saveState()
        if firmenname:
            canvas.setFont("Helvetica-Bold", 11)
            canvas.setFillColor(colors.black)
            canvas.drawCentredString(breite / 2, hoehe - 12 * mm, firmenname)
        if logo_pfad:
            try:
                canvas.drawImage(
                    logo_pfad, breite - doc.rightMargin - 25 * mm, hoehe - 20 * mm,
                    width=25 * mm, height=12 * mm, preserveAspectRatio=True, anchor="n", mask="auto",
                )
            except Exception:
                pass  # fehlerhafte/fehlende Logo-Datei darf den Export nie abbrechen
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(doc.leftMargin, 10 * mm, datetime.now().strftime("%d.%m.%Y"))
        canvas.drawRightString(breite - doc.rightMargin, 10 * mm, f"Seite {doc.page}")
        canvas.restoreState()
    return zeichnen


def _firmen_adresse(firma_kontakte: list[dict]) -> str:
    return next((_adresse_text(k) for k in firma_kontakte if _adresse_text(k)), "")


def _tabellenzeilen(kontakte: list[dict]) -> list[list]:
    """Baut die Datenzeilen der Kontakttabelle: BKP-Nummer/Funktion und
    Unternehmen (Name+Adresse) erscheinen nur in der ersten Zeile eines
    Firmenblocks, jede Person danach ist eine eigene Zeile mit ihren eigenen
    Sachbearbeitung/Funktion/Telefon/Mobil/E-Mail-Werten - analog zur
    Nutzer-Vorlage (mehrere Personen derselben Firma untereinander, BKP-Nummer
    und Firma nur einmal links davor)."""
    zeilen = [[Paragraph(spalte, _STIL_KOPFZELLE) for spalte in _TABELLEN_SPALTEN]]

    for gruppe in _gruppiere_fuer_export(kontakte):
        for firmen_gruppe in gruppe["firmen"]:
            firma = firmen_gruppe["firma"]
            firma_kontakte = firmen_gruppe["kontakte"]
            firmen_adresse = _firmen_adresse(firma_kontakte)

            for i, k in enumerate(firma_kontakte):
                if i == 0:
                    bkp_zelle = Paragraph(_bkp_zellen_text(gruppe["funktion"]), _STIL_ZELLE) if gruppe["funktion"] else ""
                    unternehmen_teile = ([f"<b>{escape(firma)}</b>"] if firma else [])
                    if firmen_adresse:
                        unternehmen_teile.append(escape(firmen_adresse))
                    unternehmen_zelle = Paragraph("<br/>".join(unternehmen_teile), _STIL_ZELLE) if unternehmen_teile else ""
                else:
                    bkp_zelle = ""
                    unternehmen_zelle = ""

                name = f"{k.get('vorname', '')} {k.get('nachname', '')}".strip()
                zeilen.append([
                    bkp_zelle,
                    unternehmen_zelle,
                    Paragraph(escape(name), _STIL_ZELLE) if name else "",
                    Paragraph(escape(k["rolle"]), _STIL_ZELLE) if k.get("rolle") else "",
                    Paragraph(_telefon_liste(k, mobil=False), _STIL_ZELLE),
                    Paragraph(_telefon_liste(k, mobil=True), _STIL_ZELLE),
                    Paragraph(_email_und_web_text(k), _STIL_ZELLE),
                ])
    return zeilen


def kontakte_pdf(ordner_name: str, kontakte: list[dict], firmenname: str = "", logo_pfad: str = "") -> bytes:
    """firmenname/logo_pfad sind optional und kommen aus den Einstellungen
    (web/export.py) - erscheinen auf jeder Seite oben (Firmenname mittig,
    Logo rechts). Der Ordnername bleibt der alleinige Titel der Liste (z.B.
    Projektname) - andere Ordner, denen ein Kontakt sonst noch angehoert,
    werden nirgends aufgefuehrt."""
    puffer = io.BytesIO()
    doc = SimpleDocTemplate(
        puffer, pagesize=landscape(A4),
        topMargin=24 * mm, bottomMargin=16 * mm, leftMargin=15 * mm, rightMargin=15 * mm,
        title=f"Rubrica – {ordner_name}",
    )
    elemente = [
        Paragraph(escape(ordner_name), _STIL_TITEL),
        Paragraph(
            f"Rubrica – Kontaktliste – {len(kontakte)} Kontakt(e) – "
            f"erzeugt am {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            _STIL_UNTERTITEL,
        ),
    ]

    if kontakte:
        tabelle = Table(
            _tabellenzeilen(kontakte),
            colWidths=[doc.width * anteil for anteil in _SPALTEN_ANTEILE],
            repeatRows=1,
        )
        tabelle.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3437")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elemente.append(tabelle)
    else:
        elemente.append(Paragraph("Dieser Ordner enthält keine Kontakte.", _STIL_ZELLE))

    zeichnen = _kopf_fuss_zeichner(firmenname, logo_pfad)
    doc.build(elemente, onFirstPage=zeichnen, onLaterPages=zeichnen)
    return puffer.getvalue()
