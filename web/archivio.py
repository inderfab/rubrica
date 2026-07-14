"""Phase 4: Vorschau + Uebernahme von Archivio-Kontaktvorschlaegen aus der Archivio-
Signatur-DB (Tabelle signatur_quelle). Vorschau liest (und markiert Status, siehe
archivio_bridge.anbindung), Uebernahme schreibt in die Review-Queue
(vorschlaege, quelle='archivio') - nie direkt in kontakte."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse

from archivio_bridge.anbindung import hole_kandidaten, liste_postfaecher, markiere_status
from config import settings
from db import queries
from db.connection import get_connection
from web.shared import templates

router = APIRouter()


def _signatur_db_pfad() -> str:
    return settings.get("archivio.signatur_db_path", "") or ""


def _hole_kandidaten_oder_leer(conn, postfaecher: List[str]):
    db_pfad = _signatur_db_pfad()
    if not db_pfad:
        return [], "Keine Archivio-Signatur-Datenbank konfiguriert (archivio.signatur_db_path in den Einstellungen)."
    min_mails = settings.get("archivio.min_mails", 2)
    try:
        return hole_kandidaten(db_pfad, conn, min_mails=min_mails, postfaecher=postfaecher or None), ""
    except Exception as exc:
        return [], f"Archivio-Signatur-Datenbank nicht lesbar: {type(exc).__name__}"


def _postfaecher_oder_leer() -> list:
    db_pfad = _signatur_db_pfad()
    if not db_pfad:
        return []
    try:
        return liste_postfaecher(db_pfad)
    except Exception:
        return []


@router.get("/archivio-import")
def archivio_import_seite(request: Request, postfaecher: List[str] = Query(default=[])):
    conn = get_connection()
    try:
        kandidaten, fehler = _hole_kandidaten_oder_leer(conn, postfaecher)
        alle_postfaecher = _postfaecher_oder_leer()
        ordner = queries.list_projekte(conn)
        zuordnungen = queries.postfach_zuordnungen(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("archivio_import.html", {
        "request": request, "kandidaten": kandidaten, "fehler": fehler,
        "alle_postfaecher": alle_postfaecher, "ausgewaehlte_postfaecher": set(postfaecher),
        "ordner": ordner, "zuordnungen": zuordnungen,
    })


@router.post("/archivio-import/postfach-zuordnen")
async def archivio_postfach_zuordnen(request: Request):
    form = await request.form()
    postfach = form.get("postfach", "").strip()
    projekt_id_roh = form.get("projekt_id", "").strip()
    projekt_id = int(projekt_id_roh) if projekt_id_roh else None
    conn = get_connection()
    try:
        queries.postfach_zuordnen(conn, postfach, projekt_id)
    finally:
        conn.close()
    return RedirectResponse(url="/archivio-import", status_code=303)


@router.post("/archivio-import/uebernehmen")
async def archivio_uebernehmen(request: Request):
    """Uebernimmt ALLE aktuell angezeigten Kandidaten auf einmal in die Review-Queue."""
    form = await request.form()
    postfaecher = form.getlist("postfaecher")
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        for daten in kandidaten:
            daten.pop("anzahl_mails", None)
            absender_email = daten.pop("absender_email", None)
            queries.create_vorschlag(conn, daten, quelle="archivio")
            if absender_email:
                markiere_status(_signatur_db_pfad(), absender_email, "uebernommen")
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.post("/archivio-import/uebernehmen-einzeln")
async def archivio_uebernehmen_einzeln(request: Request, email: str = Form(...)):
    """Uebernimmt genau EINEN Kandidaten (identifiziert per E-Mail-Adresse -
    die ist durch die strenge Vollstaendigkeitspruefung in hole_kandidaten immer
    vorhanden) als offenen Vorschlag in die Review-Queue."""
    form = await request.form()
    postfaecher = form.getlist("postfaecher")
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        for daten in kandidaten:
            if daten["emails"] and daten["emails"][0]["email"].lower() == email.lower():
                daten.pop("anzahl_mails", None)
                absender_email = daten.pop("absender_email", None)
                queries.create_vorschlag(conn, daten, quelle="archivio")
                if absender_email:
                    markiere_status(_signatur_db_pfad(), absender_email, "uebernommen")
                break
    finally:
        conn.close()
    return RedirectResponse(url="/archivio-import", status_code=303)


@router.post("/archivio-import/ablehnen")
async def archivio_ablehnen(request: Request, email: str = Form(...)):
    """Lehnt genau EINEN Kandidaten ab - legt ihn als bereits 'abgelehnt' markierten
    Vorschlag an (damit er bei der naechsten Vorschau nicht wieder auftaucht) und
    markiert die zugrundeliegenden Mails in der Archivio-DB ebenfalls als 'abgelehnt'."""
    form = await request.form()
    postfaecher = form.getlist("postfaecher")
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        for daten in kandidaten:
            if daten["emails"] and daten["emails"][0]["email"].lower() == email.lower():
                daten.pop("anzahl_mails", None)
                absender_email = daten.pop("absender_email", None)
                vorschlag_id = queries.create_vorschlag(conn, daten, quelle="archivio")
                queries.set_vorschlag_status(conn, vorschlag_id, "abgelehnt")
                if absender_email:
                    markiere_status(_signatur_db_pfad(), absender_email, "abgelehnt")
                break
    finally:
        conn.close()
    return RedirectResponse(url="/archivio-import", status_code=303)
