"""Phase 4 (Vorstufe): Vorschau + Uebernahme von Archivio-Kontaktvorschlaegen.
Vorschau liest nur (siehe archivio_bridge.anbindung), Uebernahme schreibt in die
Review-Queue (vorschlaege, quelle='archivio') - nie direkt in kontakte."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from archivio_bridge.anbindung import hole_kandidaten
from config import settings
from db import queries
from db.connection import get_connection
from web.shared import templates

router = APIRouter()


def _bereits_vorgeschlagen(conn, email: str) -> bool:
    for v in queries.list_vorschlaege(conn, status="offen"):
        if v["quelle"] != "archivio":
            continue
        for e in v["rohdaten"].get("emails", []):
            if e.get("email", "").lower() == email:
                return True
    return False


@router.get("/review/archivio-vorschau")
def archivio_vorschau(request: Request):
    db_pfad = settings.get("archivio.db_path", "")
    min_mails = settings.get("archivio.min_mails", 2)
    fehler = ""
    kandidaten = []
    if not db_pfad:
        fehler = "Keine Archivio-Datenbank konfiguriert (archivio.db_path in config.yaml)."
    else:
        conn = get_connection()
        try:
            try:
                kandidaten = hole_kandidaten(db_pfad, conn, min_mails=min_mails)
            except Exception as exc:
                fehler = f"Archivio-Datenbank nicht lesbar: {type(exc).__name__}"
        finally:
            conn.close()
    return templates.TemplateResponse("archivio_vorschau.html", {
        "request": request, "kandidaten": kandidaten, "fehler": fehler,
    })


@router.post("/review/archivio-uebernehmen")
def archivio_uebernehmen():
    db_pfad = settings.get("archivio.db_path", "")
    min_mails = settings.get("archivio.min_mails", 2)
    if not db_pfad:
        return RedirectResponse(url="/review/archivio-vorschau", status_code=303)

    conn = get_connection()
    try:
        kandidaten = hole_kandidaten(db_pfad, conn, min_mails=min_mails)
        erzeugt = 0
        for daten in kandidaten:
            email = daten["emails"][0]["email"].lower() if daten["emails"] else ""
            if email and _bereits_vorgeschlagen(conn, email):
                continue
            daten.pop("anzahl_mails", None)
            queries.create_vorschlag(conn, daten, quelle="archivio")
            erzeugt += 1
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)
