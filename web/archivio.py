"""Phase 4 (Vorstufe): Vorschau + Uebernahme von Archivio-Kontaktvorschlaegen.
Vorschau liest nur (siehe archivio_bridge.anbindung), Uebernahme schreibt in die
Review-Queue (vorschlaege, quelle='archivio') - nie direkt in kontakte."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from archivio_bridge.anbindung import hole_kandidaten
from config import settings
from db import queries
from db.connection import get_connection
from web.shared import templates

router = APIRouter()


def _hole_kandidaten_oder_leer(conn):
    db_pfad = settings.get("archivio.db_path", "")
    if not db_pfad:
        return [], "Keine Archivio-Datenbank konfiguriert (archivio.db_path in config.yaml)."
    min_mails = settings.get("archivio.min_mails", 2)
    try:
        return hole_kandidaten(db_pfad, conn, min_mails=min_mails), ""
    except Exception as exc:
        return [], f"Archivio-Datenbank nicht lesbar: {type(exc).__name__}"


@router.get("/review/archivio-vorschau")
def archivio_vorschau(request: Request):
    conn = get_connection()
    try:
        kandidaten, fehler = _hole_kandidaten_oder_leer(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("archivio_vorschau.html", {
        "request": request, "kandidaten": kandidaten, "fehler": fehler,
    })


@router.post("/review/archivio-uebernehmen")
def archivio_uebernehmen():
    """Uebernimmt ALLE aktuell angezeigten Kandidaten auf einmal."""
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn)
        for daten in kandidaten:
            daten.pop("anzahl_mails", None)
            queries.create_vorschlag(conn, daten, quelle="archivio")
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.post("/review/archivio-uebernehmen-einzeln")
def archivio_uebernehmen_einzeln(email: str = Form(...)):
    """Uebernimmt genau EINEN Kandidaten (identifiziert per E-Mail-Adresse -
    die ist durch die strenge Vollstaendigkeitspruefung in hole_kandidaten immer
    vorhanden) als offenen Vorschlag in die Review-Queue."""
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn)
        for daten in kandidaten:
            if daten["emails"] and daten["emails"][0]["email"].lower() == email.lower():
                daten.pop("anzahl_mails", None)
                queries.create_vorschlag(conn, daten, quelle="archivio")
                break
    finally:
        conn.close()
    return RedirectResponse(url="/review/archivio-vorschau", status_code=303)


@router.post("/review/archivio-ablehnen")
def archivio_ablehnen(email: str = Form(...)):
    """Lehnt genau EINEN Kandidaten ab - legt ihn als bereits 'abgelehnt' markierten
    Vorschlag an, damit er bei der naechsten Vorschau nicht wieder auftaucht
    (siehe archivio_bridge.anbindung._BestehenderBestand)."""
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn)
        for daten in kandidaten:
            if daten["emails"] and daten["emails"][0]["email"].lower() == email.lower():
                daten.pop("anzahl_mails", None)
                vorschlag_id = queries.create_vorschlag(conn, daten, quelle="archivio")
                queries.set_vorschlag_status(conn, vorschlag_id, "abgelehnt")
                break
    finally:
        conn.close()
    return RedirectResponse(url="/review/archivio-vorschau", status_code=303)
