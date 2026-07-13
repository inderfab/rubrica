from typing import List, Optional

from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import RedirectResponse

from db import queries
from db.connection import get_connection
from importer.signatur import parse_signatur
from sync import radicale
from web.shared import templates

router = APIRouter()

# Vordefinierte Funktionen (Fachrichtungen) fuer das Auswahlfeld - orientiert sich
# am Schweizer Baukostenplan (BKP), damit "Funktion" dieselbe Klassifizierung
# abbildet wie die Adresslisten, die Bauherren/Planer projektintern verwenden
# (Nutzer-Vorlage: "297.0 Geometer" usw.). Jeder Eintrag ist ein einzelner String
# "<BKP-Nummer> <Bezeichnung>" - die Combobox-Suche (app.js) filtert per
# Teilstring-Suche ueber den ganzen String, findet einen Eintrag also sowohl ueber
# die Nummer ("297") als auch ueber die Bezeichnung ("geometer"). Rollen ohne
# BKP-Klassierung (Bauherrschaft, Behoerde, intern) bleiben ohne Nummer. Freitext
# bleibt moeglich, die Liste ist nur Vorschlag, kein Zwang. Technisch im
# bestehenden Feld kontakte.kategorie gespeichert (UI-Label "Funktion").
FUNKTIONEN = [
    # Ohne BKP-Nummer (Rollen ohne Kostenklassierung)
    "Bauherrschaft/Kundschaft", "Bauherrenvertretung", "Behörde/Amt", "Lieferant/in", "intern",

    # BKP 1/2 - Vorbereitungs-, Bau- und Ausbauarbeiten (Unternehmer/Handwerker)
    "104 Baugespann",
    "111 Bodenuntersuchung/Baugrunduntersuchung",
    "149.1 Baumeisterarbeiten",
    "157 Fernwärme",
    "201 Baugrubenaushub inkl. Entsorgung",
    "211 Baumeisterarbeiten",
    "215.2 Fassadenbau",
    "221 Fenster, Aussentüren",
    "225 Metallbau",
    "226 Spenglerarbeiten",
    "227 Bedachungsarbeiten",
    "230 Starkstromanlagen",
    "231 Starkstromanlagen, Trafo",
    "232 Starkstromanlagen",
    "233 Schwachstromanlagen",
    "242 Heizungs- und Kälteanlagen",
    "244 Lufttechnische Anlagen",
    "250 Sanitäranlagen",
    "257 Sprinkleranlagen",
    "261 Aufzüge",
    "271 Bodenbeläge",
    "275 Türen, Tore",
    "276 Schreinerarbeiten",
    "359.1 Spez. Medien",
    "365 Hebeeinrichtungen",

    # BKP 29x - Planungs- und Ingenieurhonorare
    "290 Bauherrenberatung",
    "291 Generalplaner/in",
    "291 Bauleitung",
    "291 Architekt/in",
    "292 Bauingenieur/in",
    "293 Elektroingenieur/in",
    "294 HLK-Ingenieur/in",
    "295 Sanitäringenieur/in",
    "297.0 Geometer",
    "297.1 Geologe/in, Geotechniker/in",
    "297.3 Bauphysiker/in",
    "297.7 Fassadeningenieur/in",
    "298.3 Prüfingenieur/in",
    "298.5 Brandschutzingenieur/in",
    "298.6 Gaslager- und Gefahrenstoffexperte/in",
    "299 Sicherheitsbeauftragte/r",
    "299 Sicherheitsplaner/in",
    "299 Umweltberater/in",
    "299 Beleuchtungsplaner/in",
    "299 Visualisierung",

    # BKP 4 - Umgebung
    "496 Landschaftsarchitekt/in",

    # BKP 5 - Baunebenkosten
    "511 Bewilligungen, Gebühren",
    "511 Tiefbauamt",
    "512.1 Elektrizität",
    "512.4 Wasser",
    "525 Dokumentation",
    "532 Spezialversicherungen",
    "568 Baureklame",
    "598.0 Bauherrenberater",

    # Projektspezifische Sondernummern ausserhalb des Standard-BKP (aus der Praxis
    # uebernommen - Bueros vergeben teils eigene Nummern fuer Spezialfaelle)
    "601.1 Kardex-Liftsysteme",
    "601.2 Kleingüteraufzug",
    "701.1 Adaptive Solarfassade",
    "999 Nachbar",
]

# Scalar-Felder, die per Mehrfachauswahl gemeinsam bearbeitet werden koennen -
# Telefonnummern/E-Mails/Adressen/URLs/Ordner bleiben bewusst aussen vor (kein
# klares "gleich oder verschieden"-Konzept bei unterschiedlicher Anzahl je Kontakt).
FELDER_MEHRFACHBEARBEITUNG = ["vorname", "nachname", "firma", "rolle", "kategorie", "notizen"]

# Vordefinierte Kategorien fuer Telefonnummern/E-Mails - ersetzt die bisherigen
# uneinheitlichen Werte (teils deutsch "arbeit"/"mobil"/"privat", teils englisch
# aus Apple-Importen "work"/"cell"/"home"). Drei Kategorien reichen fuer den
# Export (Direkt/Allgemein sind immer sichtbar, Privat ist optional - siehe
# export/generator.py). Freitext bleibt ueber die Combobox weiterhin moeglich.
TELEFON_EMAIL_TYPEN = ["Direkt", "Privat", "Allgemein"]


def _funktion_optionen(conn) -> list:
    """Vordefinierte Funktionen + bereits im Bestand vorkommende Zusatzwerte."""
    bestehende = {
        r["kategorie"] for r in conn.execute(
            "SELECT DISTINCT kategorie FROM kontakte WHERE kategorie != ''"
        )
    }
    return FUNKTIONEN + sorted(bestehende - set(FUNKTIONEN))


def _telefon_typ_optionen(conn) -> list:
    bestehende = {
        r["typ"] for r in conn.execute("SELECT DISTINCT typ FROM telefonnummern WHERE typ != ''")
    }
    return TELEFON_EMAIL_TYPEN + sorted(bestehende - set(TELEFON_EMAIL_TYPEN))


def _email_typ_optionen(conn) -> list:
    bestehende = {
        r["typ"] for r in conn.execute("SELECT DISTINCT typ FROM emails WHERE typ != ''")
    }
    return TELEFON_EMAIL_TYPEN + sorted(bestehende - set(TELEFON_EMAIL_TYPEN))


def _parse_kontakt_form(form) -> dict:
    telefon_typen = form.getlist("telefon_typ")
    telefon_nummern = form.getlist("telefon_nummer")
    email_typen = form.getlist("email_typ")
    email_adressen = form.getlist("email_adresse")
    adresse_typen = form.getlist("adresse_typ")
    adresse_strassen = form.getlist("adresse_strasse")
    adresse_plz = form.getlist("adresse_plz")
    adresse_orte = form.getlist("adresse_ort")
    adresse_regionen = form.getlist("adresse_region")
    adresse_laender = form.getlist("adresse_land")
    url_typen = form.getlist("url_typ")
    url_adressen = form.getlist("url_adresse")

    adressen = [
        {"typ": typ.strip() or "arbeit", "strasse": strasse.strip(), "plz": plz.strip(),
         "ort": ort.strip(), "region": region.strip(), "land": land.strip()}
        for typ, strasse, plz, ort, region, land in zip(
            adresse_typen, adresse_strassen, adresse_plz, adresse_orte, adresse_regionen, adresse_laender
        )
        if strasse.strip() or plz.strip() or ort.strip()
    ]

    return {
        "vorname": form.get("vorname", "").strip(),
        "nachname": form.get("nachname", "").strip(),
        "firma": form.get("firma", "").strip(),
        "rolle": form.get("rolle", "").strip(),
        "kategorie": form.get("kategorie", "").strip(),
        "notizen": form.get("notizen", "").strip(),
        "telefonnummern": [
            {"typ": t.strip() or "Direkt", "nummer": n.strip()}
            for t, n in zip(telefon_typen, telefon_nummern) if n.strip()
        ],
        "emails": [
            {"typ": t.strip() or "Direkt", "email": e.strip()}
            for t, e in zip(email_typen, email_adressen) if e.strip()
        ],
        "adressen": adressen,
        "urls": [
            {"typ": t.strip() or "homepage", "url": u.strip()}
            for t, u in zip(url_typen, url_adressen) if u.strip()
        ],
    }


@router.get("/kontakte")
def kontakte_liste(request: Request, suche: str = "", ordner_id: str = "", kategorie: str = ""):
    ordner_id_int: Optional[int] = int(ordner_id) if ordner_id else None
    conn = get_connection()
    try:
        kontakte = queries.list_kontakte(conn, suche=suche, projekt_id=ordner_id_int, kategorie=kategorie)
        ordner = queries.list_projekte(conn)
        for o in ordner:
            o["anzahl_kontakte"] = conn.execute(
                "SELECT COUNT(*) FROM kontakte_projekte WHERE projekt_id = ?", (o["id"],)
            ).fetchone()[0]
        kategorien = sorted({k["kategorie"] for k in conn.execute("SELECT DISTINCT kategorie FROM kontakte WHERE kategorie != ''")})
    finally:
        conn.close()
    return templates.TemplateResponse("contacts_list.html", {
        "request": request, "kontakte": kontakte, "ordner": ordner,
        "kategorien": kategorien, "suche": suche, "ordner_id": ordner_id_int, "kategorie": kategorie,
    })


@router.post("/kontakte/{kontakt_id}/ordner/{ordner_id}/hinzufuegen")
def kontakt_ordner_hinzufuegen(kontakt_id: int, ordner_id: int):
    """Fuegt einen Kontakt einem Ordner hinzu (Drag&Drop in der Kontaktliste) -
    ergaenzt bestehende Ordner-Zuordnungen, ersetzt sie nicht."""
    conn = get_connection()
    try:
        queries.add_kontakt_projekt(conn, kontakt_id, ordner_id)
        radicale.push_kontakt(conn, kontakt_id)
        radicale.push_projekt(conn, ordner_id)
    finally:
        conn.close()
    return Response(status_code=204)


@router.get("/kontakte/neu")
def kontakt_neu_form(request: Request):
    conn = get_connection()
    try:
        ordner = queries.list_projekte(conn)
        funktionen = _funktion_optionen(conn)
        telefon_typen = _telefon_typ_optionen(conn)
        email_typen = _email_typ_optionen(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("contact_new.html", {
        "request": request, "ordner": ordner, "funktionen": funktionen,
        "telefon_typen": telefon_typen, "email_typen": email_typen,
        "kontakt": None, "ausgewaehlte_ordner": [],
    })


@router.post("/kontakte/signatur-parsen")
async def kontakt_signatur_parsen(request: Request):
    """htmx-Endpoint: nimmt eine hineinkopierte Signatur, gibt das vorbefuellte
    Feld-Fragment zurueck (wird ins Formular eingeschwenkt)."""
    form = await request.form()
    daten = parse_signatur(form.get("signatur", ""))
    conn = get_connection()
    try:
        ordner = queries.list_projekte(conn)
        funktionen = _funktion_optionen(conn)
        telefon_typen = _telefon_typ_optionen(conn)
        email_typen = _email_typ_optionen(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("_kontakt_felder.html", {
        "request": request, "kontakt": daten, "ordner": ordner,
        "funktionen": funktionen, "telefon_typen": telefon_typen, "email_typen": email_typen,
        "ausgewaehlte_ordner": [],
    })


@router.post("/kontakte/neu")
async def kontakt_neu_speichern(request: Request):
    form = await request.form()
    daten = _parse_kontakt_form(form)
    ordner_ids = [int(o) for o in form.getlist("ordner_ids")]
    conn = get_connection()
    try:
        kontakt_id = queries.create_kontakt(conn, daten)
        queries.set_kontakt_projekte(conn, kontakt_id, ordner_ids)
        radicale.push_kontakt(conn, kontakt_id)
        for oid in ordner_ids:
            radicale.push_projekt(conn, oid)
    finally:
        conn.close()
    return RedirectResponse(url="/kontakte", status_code=303)


def _liste_url(zurueck_ordner_id: str) -> str:
    """Baut die URL zur Kontaktliste, die zu einem zuvor aktiven Ordner-Filter
    zurueckkehrt statt immer auf "Alle Kontakte" zu springen."""
    if zurueck_ordner_id:
        return f"/kontakte?ordner_id={zurueck_ordner_id}"
    return "/kontakte"


@router.get("/kontakte/{kontakt_id}/bearbeiten")
def kontakt_bearbeiten_form(request: Request, kontakt_id: int, ordner_id: str = ""):
    conn = get_connection()
    try:
        kontakt = queries.get_kontakt(conn, kontakt_id)
        ordner = queries.list_projekte(conn)
        funktionen = _funktion_optionen(conn)
        telefon_typen = _telefon_typ_optionen(conn)
        email_typen = _email_typ_optionen(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("contact_form.html", {
        "request": request, "kontakt": kontakt, "ordner": ordner, "funktionen": funktionen,
        "telefon_typen": telefon_typen, "email_typen": email_typen,
        "action": f"/kontakte/{kontakt_id}/bearbeiten", "modal": False,
        "zurueck_ordner_id": ordner_id,
    })


@router.get("/kontakte/{kontakt_id}/bearbeiten-flyover")
def kontakt_bearbeiten_flyover(request: Request, kontakt_id: int, ordner_id: str = ""):
    """Wie kontakt_bearbeiten_form, liefert aber nur das Formular-Fragment fuer
    den Flyover (htmx laedt es in ein Overlay statt die Seite zu wechseln)."""
    conn = get_connection()
    try:
        kontakt = queries.get_kontakt(conn, kontakt_id)
        ordner = queries.list_projekte(conn)
        funktionen = _funktion_optionen(conn)
        telefon_typen = _telefon_typ_optionen(conn)
        email_typen = _email_typ_optionen(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("kontakt_bearbeiten_modal.html", {
        "request": request, "kontakt": kontakt, "ordner": ordner, "funktionen": funktionen,
        "telefon_typen": telefon_typen, "email_typen": email_typen,
        "action": f"/kontakte/{kontakt_id}/bearbeiten", "modal": True,
        "zurueck_ordner_id": ordner_id,
    })


@router.post("/kontakte/{kontakt_id}/bearbeiten")
async def kontakt_bearbeiten_speichern(request: Request, kontakt_id: int):
    form = await request.form()
    daten = _parse_kontakt_form(form)
    ordner_ids = [int(o) for o in form.getlist("ordner_ids")]
    zurueck_ordner_id = form.get("zurueck_ordner_id", "").strip()
    conn = get_connection()
    try:
        alte_ordner_ids = {o["id"] for o in queries.get_kontakt(conn, kontakt_id)["projekte"]}
        queries.update_kontakt(conn, kontakt_id, daten)
        queries.set_kontakt_projekte(conn, kontakt_id, ordner_ids)
        radicale.push_kontakt(conn, kontakt_id)
        for oid in alte_ordner_ids | set(ordner_ids):
            radicale.push_projekt(conn, oid)
    finally:
        conn.close()
    return RedirectResponse(url=_liste_url(zurueck_ordner_id), status_code=303)


@router.post("/kontakte/{kontakt_id}/loeschen")
def kontakt_loeschen(kontakt_id: int, zurueck_ordner_id: str = Form("")):
    conn = get_connection()
    try:
        betroffene_ordner_ids = {o["id"] for o in queries.get_kontakt(conn, kontakt_id)["projekte"]}
        queries.delete_kontakt(conn, kontakt_id)
        radicale.delete_kontakt(kontakt_id)
        for oid in betroffene_ordner_ids:
            radicale.push_projekt(conn, oid)
    finally:
        conn.close()
    return RedirectResponse(url=_liste_url(zurueck_ordner_id), status_code=303)


@router.get("/kontakte/bulk-bearbeiten-flyover")
def kontakte_bulk_bearbeiten_flyover(request: Request, ids: List[int] = Query(...), ordner_id: str = ""):
    """Sammel-Bearbeiten fuer mehrere ausgewaehlte Kontakte: fuer jedes Scalar-Feld
    wird geprueft, ob alle ausgewaehlten Kontakte denselben Wert haben (vorausgefuellt,
    editierbar) oder ob sich die Werte unterscheiden ("Unterschiedliche Werte" -
    Feld bleibt leer, ein __gemischt-Flag merkt sich das fuer die Auswertung beim
    Speichern: nur explizit ausgefuellte Felder werden dann fuer alle uebernommen)."""
    conn = get_connection()
    try:
        kontakte = [queries.get_kontakt(conn, kid) for kid in ids]
        ordner = queries.list_projekte(conn)
        funktionen = _funktion_optionen(conn)
    finally:
        conn.close()

    felder = {}
    for feld in FELDER_MEHRFACHBEARBEITUNG:
        werte = {k[feld] for k in kontakte}
        if len(werte) == 1:
            felder[feld] = {"wert": werte.pop(), "gemischt": False}
        else:
            felder[feld] = {"wert": "", "gemischt": True}

    return templates.TemplateResponse("kontakt_bulk_bearbeiten_modal.html", {
        "request": request, "kontakte": kontakte, "ids": ids, "felder": felder,
        "ordner": ordner, "funktionen": funktionen, "zurueck_ordner_id": ordner_id,
        "telefon_email_typen": TELEFON_EMAIL_TYPEN,
    })


@router.post("/kontakte/bulk-bearbeiten")
async def kontakte_bulk_bearbeiten_speichern(request: Request):
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids")]
    zurueck_ordner_id = form.get("zurueck_ordner_id", "").strip()

    felder = {}
    for feld in FELDER_MEHRFACHBEARBEITUNG:
        war_gemischt = form.get(f"{feld}__gemischt", "") == "1"
        wert = form.get(feld, "").strip()
        if war_gemischt and not wert:
            continue  # unangetastetes "Unterschiedliche Werte"-Feld: nichts aendern
        felder[feld] = wert

    conn = get_connection()
    try:
        betroffene_ordner_ids = set()
        for kontakt_id in ids:
            if felder:
                queries.update_kontakt_felder(conn, kontakt_id, felder)
            betroffene_ordner_ids |= {o["id"] for o in queries.get_kontakt(conn, kontakt_id)["projekte"]}
            radicale.push_kontakt(conn, kontakt_id)
        for oid in betroffene_ordner_ids:
            radicale.push_projekt(conn, oid)
    finally:
        conn.close()
    return RedirectResponse(url=_liste_url(zurueck_ordner_id), status_code=303)


@router.post("/kontakte/bulk-kategorie-umstellen")
async def kontakte_bulk_kategorie_umstellen(request: Request):
    """Stellt bei allen ausgewaehlten Kontakten Telefonnummern/E-Mails einer
    Kategorie (Direkt/Privat/Allgemein) auf eine andere um - bewusst getrennt
    vom generischen Sammel-Bearbeiten oben: Telefonnummern/E-Mails haben pro
    Kontakt unterschiedlich viele Eintraege, ein positionsbasiertes Bearbeiten
    der Werte selbst ergibt dort keinen klaren Sinn (siehe docs/konzept.md)."""
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids")]
    zurueck_ordner_id = form.get("zurueck_ordner_id", "").strip()
    feld = form.get("feld", "").strip()
    von = form.get(f"{feld}_von", "").strip()
    nach = form.get(f"{feld}_nach", "").strip()

    if feld in ("telefon", "email") and von and nach and von != nach:
        conn = get_connection()
        try:
            for kontakt_id in ids:
                queries.kategorie_umstellen(conn, feld, kontakt_id, von, nach)
                radicale.push_kontakt(conn, kontakt_id)
        finally:
            conn.close()
    return RedirectResponse(url=_liste_url(zurueck_ordner_id), status_code=303)
