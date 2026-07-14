from __future__ import annotations

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import RedirectResponse

from db.connection import get_connection
from importer.vcard import importiere
from sync import radicale
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
    wurde; ohne solche Daten passiert einfach nichts). Kontakte werden direkt
    angelegt bzw. gemergt (keine Review-Queue mehr) - Korrekturen erfolgen
    danach direkt am Kontakt."""
    conn = get_connection()
    try:
        kontakt_ids = []
        for datei in dateien:
            inhalt = (await datei.read()).decode("utf-8", errors="replace")
            kontakt_ids.extend(importiere(conn, inhalt))
        for kontakt_id in set(kontakt_ids):
            radicale.push_kontakt_mit_ordnern(conn, kontakt_id)
    finally:
        conn.close()

    return RedirectResponse(url="/kontakte", status_code=303)
