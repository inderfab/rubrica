"""Einstellungsseite - fuer Konfigurationswerte, die bisher nur per Hand in
config.yaml editierbar waren (z.B. Archivio-Anbindung). Vermeidet, dass Nutzer
YAML von Hand bearbeiten muessen (Fehlerquelle: Tippfehler, falsche Einrueckung,
fehlende Sektion bei Installationen mit aelterem config.yaml)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from config import settings
from web.shared import templates

router = APIRouter()


@router.get("/einstellungen")
def einstellungen_form(request: Request, gespeichert: str = ""):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "gespeichert": bool(gespeichert),
        "archivio_db_path": settings.get("archivio.db_path", "") or "",
        "archivio_min_mails": settings.get("archivio.min_mails", 2),
        "backup_pfad": settings.get("backup.pfad", "") or "",
    })


@router.post("/einstellungen")
async def einstellungen_speichern(request: Request):
    form = await request.form()
    db_path = (form.get("archivio_db_path") or "").strip()
    try:
        min_mails = int(form.get("archivio_min_mails") or 2)
    except ValueError:
        min_mails = 2
    backup_pfad = (form.get("backup_pfad") or "").strip()

    settings.save({
        "archivio": {"db_path": db_path, "min_mails": min_mails},
        "backup": {"pfad": backup_pfad},
    })
    return RedirectResponse(url="/einstellungen?gespeichert=1", status_code=303)
