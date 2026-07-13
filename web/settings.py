"""Einstellungsseite - fuer Konfigurationswerte, die bisher nur per Hand in
config.yaml editierbar waren (z.B. Archivio-Anbindung). Vermeidet, dass Nutzer
YAML von Hand bearbeiten muessen (Fehlerquelle: Tippfehler, falsche Einrueckung,
fehlende Sektion bei Installationen mit aelterem config.yaml)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from config import settings
from web.shared import templates

router = APIRouter()

LOGO_ERLAUBTE_ENDUNGEN = {".png", ".jpg", ".jpeg", ".gif"}


def _logo_entfernen() -> None:
    for alte_datei in settings.daten_verzeichnis().glob(f"{settings.LOGO_STAMM}.*"):
        alte_datei.unlink(missing_ok=True)


@router.get("/einstellungen")
def einstellungen_form(request: Request, gespeichert: str = ""):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "gespeichert": bool(gespeichert),
        "archivio_db_path": settings.get("archivio.db_path", "") or "",
        "archivio_min_mails": settings.get("archivio.min_mails", 2),
        "backup_pfad": settings.get("backup.pfad", "") or "",
        "export_firmenname": settings.get("export.firmenname", "") or "",
        "logo_vorhanden": settings.logo_pfad() is not None,
        "privates_telefon_zeigen": bool(settings.get("export.privates_telefon_zeigen", False)),
        "private_email_zeigen": bool(settings.get("export.private_email_zeigen", False)),
        "privatadresse_zeigen": bool(settings.get("export.privatadresse_zeigen", False)),
        "radicale_base_url": settings.get("radicale.base_url", "") or "",
        "radicale_addressbook_path": settings.get("radicale.addressbook_path", "") or "",
        "radicale_username": settings.get("radicale.username", "") or "",
        "radicale_password": settings.get("radicale.password", "") or "",
        "radicale_verify_ssl": bool(settings.get("radicale.verify_ssl", True)),
    })


@router.get("/einstellungen/logo")
def einstellungen_logo():
    pfad = settings.logo_pfad()
    if pfad is None:
        return Response(status_code=404)
    return FileResponse(pfad)


@router.post("/einstellungen/logo/entfernen")
def einstellungen_logo_entfernen():
    _logo_entfernen()
    return RedirectResponse(url="/einstellungen?gespeichert=1", status_code=303)


@router.post("/einstellungen")
async def einstellungen_speichern(request: Request):
    form = await request.form()
    db_path = (form.get("archivio_db_path") or "").strip()
    try:
        min_mails = int(form.get("archivio_min_mails") or 2)
    except ValueError:
        min_mails = 2
    backup_pfad = (form.get("backup_pfad") or "").strip()
    export_firmenname = (form.get("export_firmenname") or "").strip()
    radicale_base_url = (form.get("radicale_base_url") or "").strip()
    radicale_addressbook_path = (form.get("radicale_addressbook_path") or "").strip()
    radicale_username = (form.get("radicale_username") or "").strip()
    radicale_password = form.get("radicale_password") or ""

    logo = form.get("logo")
    if logo is not None and getattr(logo, "filename", ""):
        endung = Path(logo.filename).suffix.lower()
        if endung in LOGO_ERLAUBTE_ENDUNGEN:
            _logo_entfernen()
            ziel = settings.daten_verzeichnis() / f"{settings.LOGO_STAMM}{endung}"
            ziel.write_bytes(await logo.read())

    settings.save({
        "archivio": {"db_path": db_path, "min_mails": min_mails},
        "backup": {"pfad": backup_pfad},
        "radicale": {
            "base_url": radicale_base_url,
            "addressbook_path": radicale_addressbook_path,
            "username": radicale_username,
            "password": radicale_password,
            "verify_ssl": form.get("radicale_verify_ssl") is not None,
        },
        "export": {
            "firmenname": export_firmenname,
            "privates_telefon_zeigen": form.get("privates_telefon_zeigen") is not None,
            "private_email_zeigen": form.get("private_email_zeigen") is not None,
            "privatadresse_zeigen": form.get("privatadresse_zeigen") is not None,
        },
    })
    return RedirectResponse(url="/einstellungen?gespeichert=1", status_code=303)
