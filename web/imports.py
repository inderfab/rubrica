from __future__ import annotations

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import RedirectResponse

from db.connection import get_connection
from importer.vcard import importiere
from sync import radicale
from web.shared import importiere_kontakte_app_und_synchronisiere, templates

router = APIRouter()


def _ist_lokal(request: Request) -> bool:
    """Der Kontakte.app-Import liest die Kontakte.app auf der Maschine, auf der
    Rubrica laeuft (osascript, serverseitig) - nicht auf dem Rechner der/des
    Zugreifenden. Ueber das Buero-LAN wuerde das versehentlich das Adressbuch
    des Servers statt des eigenen importieren, daher wie im Setup-Assistenten
    nur lokal anbieten."""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


@router.get("/import")
def import_form(request: Request):
    return templates.TemplateResponse("import_form.html", {
        "request": request, "kontakte_app_lokal": _ist_lokal(request),
    })


@router.post("/import/kontakte-app")
def import_kontakte_app(request: Request):
    if not _ist_lokal(request):
        return {"ok": False, "detail": "Nur direkt auf diesem Rechner möglich."}
    conn = get_connection()
    try:
        ergebnis = importiere_kontakte_app_und_synchronisiere(conn)
        return {"ok": True, **ergebnis}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()


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
