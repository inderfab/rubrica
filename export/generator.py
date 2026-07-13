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
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from sync.radicale import kontakt_zu_vcard

CSV_SPALTEN = [
    "Vorname", "Nachname", "Firma", "Funktion", "Rolle",
    "Telefon", "E-Mail", "Adresse", "Homepage", "Notizen",
]


def _telefon_text(kontakt: dict) -> str:
    return "; ".join(f"{t['typ']}: {t['nummer']}" for t in kontakt.get("telefonnummern", []))


_PRIVAT_TYPEN = {"privat", "private", "home", "cell", "mobil", "iphone"}


def _ist_privat_typ(typ: str) -> bool:
    return (typ or "").strip().lower() in _PRIVAT_TYPEN


def _ist_firmenkontakt(kontakt: dict) -> bool:
    """Ein Kontakt ohne Vor-/Nachname repraesentiert in der Praxis oft die Firma
    selbst (allgemeine Nummer/Mail, z.B. ein Sekretariat) statt einer Person -
    genau dieses Muster kommt im echten Bestand vor. Dessen Kontaktdaten werden
    im Export als "allgemeine" Firmenzeile gezeigt statt als Mitarbeiter-Zeile."""
    return not (kontakt.get("vorname", "").strip() or kontakt.get("nachname", "").strip())


def _direktwahl_pdf(kontakt: dict, privates_telefon_zeigen: bool) -> str:
    """Kategorien Direkt/Allgemein immer sichtbar, Privat (inkl. Mobilnummern -
    gelten als privat) nur wenn in den Export-Einstellungen aktiviert."""
    ergebnis = [
        t["nummer"] for t in kontakt.get("telefonnummern", [])
        if not (_ist_privat_typ(t.get("typ", "")) and not privates_telefon_zeigen)
    ]
    return "<br/>".join(escape(n) for n in ergebnis)


def _email_pdf(kontakt: dict, private_email_zeigen: bool) -> str:
    """Geschaeftliche/allgemeine E-Mails immer, private nur wenn aktiviert.
    Reale vCard-Importe taggen E-Mails fast immer generisch (Apple: "internet")
    - nur explizit als privat/home markierte Eintraege werden ausgeblendet,
    damit unklar getaggte Adressen nicht faelschlich verschwinden. Die
    Webseite ist bewusst NICHT Teil dieser Funktion (siehe _firmen_webseiten_pdf) -
    sie gilt firmenweit und erscheint nur einmal auf der Firmenzeile, nicht bei
    jedem Mitarbeiter."""
    ergebnis = [
        e["email"] for e in kontakt.get("emails", [])
        if not (_ist_privat_typ(e.get("typ", "")) and not private_email_zeigen)
    ]
    return "<br/>".join(escape(t) for t in ergebnis)


def _firmen_webseiten_pdf(alle_kontakte: list[dict]) -> str:
    """Sammelt alle Webseiten-URLs innerhalb einer Firmengruppe (unabhaengig
    davon, an welchem einzelnen Kontakt sie haengen) und entfernt Duplikate -
    die Webseite gilt firmenweit und wird nur einmal auf der Firmenzeile
    gezeigt, nicht bei jedem Mitarbeiter wiederholt."""
    gesehen = []
    for k in alle_kontakte:
        for u in k.get("urls", []):
            if u["url"] not in gesehen:
                gesehen.append(u["url"])
    return "<br/>".join(escape(u) for u in gesehen)


def _adresse_pdf(kontakt: dict, privatadresse_zeigen: bool) -> str:
    """Standardmaessig nur die geschaeftliche Adresse, ohne Typ-Praefix (kein
    "work"/"arbeit" im Ausdruck - der Nutzer wollte diesen Praefix nicht
    sehen). Die private Adresse erscheint nur, wenn in den Export-
    Einstellungen aktiviert, dann mit "Privat:"-Praefix zur Unterscheidung."""
    zeilen = []
    for a in kontakt.get("adressen", []):
        privat = _ist_privat_typ(a.get("typ", ""))
        if privat and not privatadresse_zeigen:
            continue
        teile = [a.get("strasse", ""), f"{a.get('plz', '')} {a.get('ort', '')}".strip()]
        teile = [t for t in teile if t]
        if a.get("land"):
            teile.append(a["land"])
        if not teile:
            continue
        text = ", ".join(teile)
        if privat:
            text = f"Privat: {text}"
        zeilen.append(text)
    return "<br/>".join(escape(z) for z in zeilen)


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
_STIL_TITEL = ParagraphStyle("OrdnerTitel", parent=_STYLES["Title"], alignment=0, spaceAfter=3 * mm)
_STIL_ZELLE = ParagraphStyle("Zelle", parent=_STYLES["Normal"], fontSize=8, leading=10)
_STIL_KOPFZELLE = ParagraphStyle(
    "Kopfzelle", parent=_STIL_ZELLE, fontName="Helvetica-Bold", textColor=colors.white,
)

_TABELLEN_SPALTEN = ["BKP Nummer", "Unternehmen", "Sachbearbeitung", "Funktion", "Telefon", "E-Mail/Webseite"]
_SPALTEN_ANTEILE = [0.13, 0.20, 0.16, 0.16, 0.16, 0.19]
_RAND = 15 * mm


class _NumberedCanvas(Canvas):
    """Speichert jede Seite zwischen, statt sie sofort zu schreiben - beim
    finalen save() ist die Gesamt-Seitenzahl bekannt, erst dann kann "Seite X
    von Y" gezeichnet werden (reportlab kennt sie waehrend des normalen
    Seitenaufbaus noch nicht, da es nur einen Durchlauf macht)."""

    def __init__(self, *args, **kwargs):
        Canvas.__init__(self, *args, **kwargs)
        self._gespeicherte_seiten = []

    def showPage(self):
        self._gespeicherte_seiten.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        gesamt = len(self._gespeicherte_seiten)
        for zustand in self._gespeicherte_seiten:
            self.__dict__.update(zustand)
            self.saveState()
            self.setFont("Helvetica", 7)
            self.setFillColor(colors.grey)
            self.drawRightString(self._pagesize[0] - _RAND, 10 * mm, f"Seite {self.getPageNumber()} von {gesamt}")
            self.restoreState()
            Canvas.showPage(self)
        Canvas.save(self)


def _bkp_zellen_text(funktion: str) -> str:
    """Bricht "292 Bauingenieur/in" nach der Nummer um ("292<br/>Bauingenieur/in")
    statt die lange Bezeichnung mitten im Wort umbrechen zu lassen (reportlab
    trennt sonst harte Wortumbrueche, sobald ein Wort allein nicht in die enge
    BKP-Spalte passt)."""
    teile = funktion.split(" ", 1)
    return "<br/>".join(escape(t) for t in teile)


def _kopf_zeichner(firmenname: str, logo_pfad: str):
    """Wird pro Seite als Canvas-Callback aufgerufen (nicht als Flowable), damit
    Firmenname/Logo/Datum auf JEDER Seite erscheinen, nicht nur auf der ersten -
    Platypus-Flowables wiederholen sich sonst nicht automatisch ueber Seiten
    hinweg. Firmenname mittig oben, Logo rechts oben (Nutzer-Vorgabe; ersetzt
    den fixen "mmt"-Platzhalter aus der Beispielvorlage), beides ueber die
    Einstellungen konfigurierbar. "Seite X von Y" zeichnet _NumberedCanvas."""
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
        canvas.drawString(doc.leftMargin, 10 * mm, f"{datetime.now().strftime('%d.%m.%Y')} / Rubrica")
        canvas.restoreState()
    return zeichnen


def _firmen_adresse_pdf(alle_kontakte: list[dict], privatadresse_zeigen: bool) -> str:
    return next((a for a in (_adresse_pdf(k, privatadresse_zeigen) for k in alle_kontakte) if a), "")


def _mitarbeiter_zeile(
    kontakt: dict, privates_telefon_zeigen: bool, private_email_zeigen: bool, bkp_zelle="",
) -> list:
    name = f"{kontakt.get('vorname', '')} {kontakt.get('nachname', '')}".strip()
    telefon = _direktwahl_pdf(kontakt, privates_telefon_zeigen)
    email = _email_pdf(kontakt, private_email_zeigen)
    return [
        bkp_zelle,
        "",
        Paragraph(escape(name), _STIL_ZELLE) if name else "",
        Paragraph(escape(kontakt["rolle"]), _STIL_ZELLE) if kontakt.get("rolle") else "",
        Paragraph(telefon, _STIL_ZELLE) if telefon else "",
        Paragraph(email, _STIL_ZELLE) if email else "",
    ]


def _tabellenzeilen(
    kontakte: list[dict], privates_telefon_zeigen: bool, private_email_zeigen: bool, privatadresse_zeigen: bool,
) -> tuple[list[list], list[int]]:
    """Baut die Datenzeilen der Kontakttabelle. Pro Firma gibt es IMMER eine
    eigene "Firmenzeile" (BKP-Nummer/Gewerk, Firmenname+Adresse, allgemeine
    Nummer/Mail/Webseite falls vorhanden - Sachbearbeitung/Funktion bleiben
    dort leer), gefolgt von je einer Zeile pro Mitarbeiter (Name/Funktion/
    Direktwahl) - exakt das Muster aus der Nutzer-Vorlage. Die "allgemeine
    Nummer/Mail" stammt von einem Kontakt ohne Namen in derselben Firma, falls
    vorhanden (siehe _ist_firmenkontakt) - gibt es keinen, bleiben die Felder
    leer. Die Webseite gilt firmenweit (siehe _firmen_webseiten_pdf) und
    erscheint deshalb NUR auf der Firmenzeile, nie bei einzelnen Mitarbeitern.
    Kontakte ohne Firma bekommen keine eigene Firmenzeile, die BKP-Nummer
    steht dann direkt auf der ersten Personenzeile.
    Gibt zusaetzlich die Zeilenindizes zurueck, an denen eine neue Firma
    beginnt (fuer die Trennlinie zwischen den Bloecken)."""
    zeilen = [[Paragraph(s, _STIL_KOPFZELLE) for s in _TABELLEN_SPALTEN]]
    gruppengrenzen = []

    for gruppe in _gruppiere_fuer_export(kontakte):
        for firmen_gruppe in gruppe["firmen"]:
            firma = firmen_gruppe["firma"]
            alle_kontakte = firmen_gruppe["kontakte"]
            bkp_zelle = Paragraph(_bkp_zellen_text(gruppe["funktion"]), _STIL_ZELLE) if gruppe["funktion"] else ""
            gruppengrenzen.append(len(zeilen))

            if firma:
                firmenkontakt = next((k for k in alle_kontakte if _ist_firmenkontakt(k)), None)
                mitarbeiter = [k for k in alle_kontakte if k is not firmenkontakt]

                adresse = _firmen_adresse_pdf(alle_kontakte, privatadresse_zeigen)
                unternehmen_teile = [f"<b>{escape(firma)}</b>"]
                if adresse:
                    unternehmen_teile.append(adresse)
                unternehmen_zelle = Paragraph("<br/>".join(unternehmen_teile), _STIL_ZELLE)

                allg_telefon = _direktwahl_pdf(firmenkontakt, privates_telefon_zeigen) if firmenkontakt else ""
                allg_email = _email_pdf(firmenkontakt, private_email_zeigen) if firmenkontakt else ""
                allg_web = _firmen_webseiten_pdf(alle_kontakte)
                allg_email_zelle = "<br/>".join(t for t in (allg_email, allg_web) if t)
                zeilen.append([
                    bkp_zelle, unternehmen_zelle, "", "",
                    Paragraph(allg_telefon, _STIL_ZELLE) if allg_telefon else "",
                    Paragraph(allg_email_zelle, _STIL_ZELLE) if allg_email_zelle else "",
                ])

                for k in mitarbeiter:
                    zeilen.append(_mitarbeiter_zeile(k, privates_telefon_zeigen, private_email_zeigen))
            else:
                for i, k in enumerate(alle_kontakte):
                    zeilen.append(_mitarbeiter_zeile(
                        k, privates_telefon_zeigen, private_email_zeigen, bkp_zelle=bkp_zelle if i == 0 else "",
                    ))
    return zeilen, gruppengrenzen


def kontakte_pdf(
    ordner_name: str, kontakte: list[dict], firmenname: str = "", logo_pfad: str = "",
    privates_telefon_zeigen: bool = False, private_email_zeigen: bool = False, privatadresse_zeigen: bool = False,
) -> bytes:
    """firmenname/logo_pfad sowie die drei zeige_*-Flags kommen aus den
    Einstellungen (web/export.py). Firmenname/Logo/Datum erscheinen auf jeder
    Seite oben/unten (Firmenname mittig, Logo rechts). Standardmaessig werden
    nur geschaeftliche Kontaktdaten gezeigt (Mobil-/Privat-Nummern, private
    E-Mail und Heimadresse sind Opt-in) - so bleibt der Export kompakt, auch
    wenn im Bestand teils private Daten hinterlegt sind. Der Ordnername bleibt
    der alleinige Titel der Liste (z.B. Projektname) - andere Ordner, denen
    ein Kontakt sonst noch angehoert, werden nirgends aufgefuehrt."""
    puffer = io.BytesIO()
    doc = SimpleDocTemplate(
        puffer, pagesize=landscape(A4),
        topMargin=24 * mm, bottomMargin=16 * mm, leftMargin=_RAND, rightMargin=_RAND,
        title=f"Rubrica – {ordner_name}",
    )
    elemente = [Paragraph(escape(ordner_name), _STIL_TITEL)]

    if kontakte:
        zeilen, gruppengrenzen = _tabellenzeilen(
            kontakte, privates_telefon_zeigen, private_email_zeigen, privatadresse_zeigen,
        )
        tabelle = Table(zeilen, colWidths=[doc.width * anteil for anteil in _SPALTEN_ANTEILE], repeatRows=1)
        stil = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3437")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        # Eine duenne Trennlinie zwischen den Firmen-/BKP-Bloecken statt eines
        # vollen Gitternetzes (Nutzer-Vorgabe: "zwischen jeder BKP eine Linie") -
        # keine Linien zwischen den Mitarbeiter-Zeilen derselben Firma.
        for zeilenindex in gruppengrenzen:
            stil.append(("LINEABOVE", (0, zeilenindex), (-1, zeilenindex), 0.5, colors.HexColor("#bbbbbb")))
        tabelle.setStyle(TableStyle(stil))
        elemente.append(tabelle)
    else:
        elemente.append(Paragraph("Dieser Ordner enthält keine Kontakte.", _STIL_ZELLE))

    zeichnen = _kopf_zeichner(firmenname, logo_pfad)
    doc.build(elemente, onFirstPage=zeichnen, onLaterPages=zeichnen, canvasmaker=_NumberedCanvas)
    return puffer.getvalue()
