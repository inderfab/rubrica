from __future__ import annotations

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import RedirectResponse

from db.connection import get_connection
from importer.vcard import importiere
from web.shared import templates

router = APIRouter()


@router.get("/import")
def import_form(request: Request):
    return templates.TemplateResponse("import_form.html", {"request": request})


@router.post("/import")
async def import_hochladen(dateien: list[UploadFile]):
    """Apple-Gruppen werden immer versucht zu uebernehmen (frueher eine
    Checkbox, die praktisch wirkungslos war - Gruppenzugehoerigkeit steht nur
    in vCards drin, wenn eine ganze Gruppe statt einzelner Kontakte exportiert
    wurde; ohne solche Daten passiert einfach nichts). Kein Risiko durch
    automatisches Anlegen: Ordner-Zuordnung landet wie alles andere erst als
    Vorschlag in der Review-Queue."""
    anzahl_gesamt = 0
    conn = get_connection()
    try:
        for datei in dateien:
            inhalt = (await datei.read()).decode("utf-8", errors="replace")
            anzahl_gesamt += importiere(conn, inhalt)
    finally:
        conn.close()

    return RedirectResponse(url="/review", status_code=303)
