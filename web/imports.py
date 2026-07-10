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
async def import_hochladen(request: Request, dateien: list[UploadFile]):
    form = await request.form()
    gruppen_als_ordner = form.get("gruppen_als_ordner") == "on"

    anzahl_gesamt = 0
    conn = get_connection()
    try:
        for datei in dateien:
            inhalt = (await datei.read()).decode("utf-8", errors="replace")
            anzahl_gesamt += importiere(conn, inhalt, gruppen_als_ordner)
    finally:
        conn.close()

    return RedirectResponse(url="/review", status_code=303)
