from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from db import queries
from db.connection import get_connection
from importer.signatur import parse_signatur
from sync import radicale
from web.shared import templates

router = APIRouter()

# Vordefinierte Funktionen (Fachrichtungen) fuer das Auswahlfeld. Freitext bleibt
# moeglich (HTML-datalist) - die Liste ist nur Vorschlag, kein Zwang. Technisch im
# bestehenden Feld kontakte.kategorie gespeichert (UI-Label "Funktion").
FUNKTIONEN = [
    "Architekt", "Innenarchitekt", "Bauingenieur/Statik", "Bauleiter",
    "Bauherr/Kunde", "Bauherrenvertreter", "Geologe", "Vermessung/Geometer",
    "Sanitärplaner", "Lüftungsplaner", "Heizungsplaner", "Elektroplaner",
    "Lichtplaner", "Türplaner", "Brandschutzplaner", "Bauphysik/Akustik",
    "Landschaftsarchitekt", "Industrieplaner", "Unternehmer/Handwerker",
    "Behörde/Amt", "Lieferant", "intern",
]


def _funktion_optionen(conn) -> list:
    """Vordefinierte Funktionen + bereits im Bestand vorkommende Zusatzwerte."""
    bestehende = {
        r["kategorie"] for r in conn.execute(
            "SELECT DISTINCT kategorie FROM kontakte WHERE kategorie != ''"
        )
    }
    return FUNKTIONEN + sorted(bestehende - set(FUNKTIONEN))


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
            {"typ": t.strip() or "mobil", "nummer": n.strip()}
            for t, n in zip(telefon_typen, telefon_nummern) if n.strip()
        ],
        "emails": [
            {"typ": t.strip() or "arbeit", "email": e.strip()}
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
    finally:
        conn.close()
    return templates.TemplateResponse("contact_new.html", {
        "request": request, "ordner": ordner, "funktionen": funktionen,
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
    finally:
        conn.close()
    return templates.TemplateResponse("_kontakt_felder.html", {
        "request": request, "kontakt": daten, "ordner": ordner,
        "funktionen": funktionen, "ausgewaehlte_ordner": [],
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


@router.get("/kontakte/{kontakt_id}/bearbeiten")
def kontakt_bearbeiten_form(request: Request, kontakt_id: int):
    conn = get_connection()
    try:
        kontakt = queries.get_kontakt(conn, kontakt_id)
        ordner = queries.list_projekte(conn)
        funktionen = _funktion_optionen(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("contact_form.html", {
        "request": request, "kontakt": kontakt, "ordner": ordner, "funktionen": funktionen,
        "action": f"/kontakte/{kontakt_id}/bearbeiten",
    })


@router.post("/kontakte/{kontakt_id}/bearbeiten")
async def kontakt_bearbeiten_speichern(request: Request, kontakt_id: int):
    form = await request.form()
    daten = _parse_kontakt_form(form)
    ordner_ids = [int(o) for o in form.getlist("ordner_ids")]
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
    return RedirectResponse(url="/kontakte", status_code=303)


@router.post("/kontakte/{kontakt_id}/loeschen")
def kontakt_loeschen(kontakt_id: int):
    conn = get_connection()
    try:
        betroffene_ordner_ids = {o["id"] for o in queries.get_kontakt(conn, kontakt_id)["projekte"]}
        queries.delete_kontakt(conn, kontakt_id)
        radicale.delete_kontakt(kontakt_id)
        for oid in betroffene_ordner_ids:
            radicale.push_projekt(conn, oid)
    finally:
        conn.close()
    return RedirectResponse(url="/kontakte", status_code=303)
