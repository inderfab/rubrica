"""Setup-Assistent fuer eine frische Installation (Kapitel 5 der
Distributionsfaehigkeit-Arbeit, siehe docs/CHANGELOG-INTERN.md). Fuehrt einmalig
durch Firmenangaben, Archivio-Domain(s), CardDAV-Einrichtung und optionale
Archivio-Anbindung - danach identisches Formular wie in den Einstellungen
(siehe web/settings.py), nur schrittweise abgefragt. Bestehende Installationen
mit bereits vorhandenen Kontakten sehen diesen Assistenten nie (siehe
web.shared._setup_erforderlich)."""
from __future__ import annotations

import socket
import sqlite3
import subprocess
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from config import settings
from sync import radicale
from web.settings import LOGO_ERLAUBTE_ENDUNGEN, _logo_entfernen
from web.shared import templates

router = APIRouter()


def _nur_lokal(request: Request) -> Response | None:
    """Der Setup-Assistent fragt u.a. das CardDAV-Passwort ab, bevor irgendein
    Zugriffsschutz eingerichtet ist - waehrend einer frischen Installation daher
    bewusst nur ueber localhost erreichbar, nicht ueber das Buero-LAN."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        return Response(status_code=403, content="Setup nur lokal auf diesem Rechner möglich.")
    return None


def _hostname_local() -> str:
    try:
        out = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5)
        name = out.stdout.strip()
    except Exception:
        name = ""
    return f"{name or socket.gethostname()}.local"


def _eigene_domains_parsen(roh: str) -> list:
    return [d.strip().lstrip("@").lower() for d in roh.split(",") if d.strip()]


@router.get("/setup/1")
def setup_schritt1(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    return templates.TemplateResponse("setup_1_willkommen.html", {"request": request})


@router.get("/setup/2")
def setup_schritt2_form(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    return templates.TemplateResponse("setup_2_firma.html", {
        "request": request,
        "export_firmenname": settings.get("export.firmenname", "") or "",
        "logo_vorhanden": settings.logo_pfad() is not None,
    })


@router.post("/setup/2")
async def setup_schritt2_speichern(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    form = await request.form()
    firmenname = (form.get("export_firmenname") or "").strip()

    logo = form.get("logo")
    if logo is not None and getattr(logo, "filename", ""):
        endung = Path(logo.filename).suffix.lower()
        if endung in LOGO_ERLAUBTE_ENDUNGEN:
            _logo_entfernen()
            ziel = settings.daten_verzeichnis() / f"{settings.LOGO_STAMM}{endung}"
            ziel.write_bytes(await logo.read())

    settings.save({"export": {"firmenname": firmenname}})
    return RedirectResponse(url="/setup/3", status_code=303)


@router.get("/setup/3")
def setup_schritt3_form(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    return templates.TemplateResponse("setup_3_domain.html", {
        "request": request,
        "archivio_eigene_domains": ", ".join(settings.get("archivio.eigene_domains", []) or []),
    })


@router.post("/setup/3")
async def setup_schritt3_speichern(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    form = await request.form()
    eigene_domains = _eigene_domains_parsen(form.get("archivio_eigene_domains") or "")
    settings.save({"archivio": {"eigene_domains": eigene_domains}})
    return RedirectResponse(url="/setup/4", status_code=303)


@router.get("/setup/4")
def setup_schritt4(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    return templates.TemplateResponse("setup_4_carddav.html", {
        "request": request,
        "hostname": _hostname_local(),
        "radicale_username": radicale.RADICALE_BENUTZER,
        "radicale_password": settings.get("radicale.password", "") or "",
    })


@router.post("/setup/carddav-test")
def setup_carddav_test(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    client = radicale._client()
    if client is None:
        return {"ok": False, "detail": "Radicale ist nicht konfiguriert (radicale.base_url fehlt)."}
    try:
        antwort = client.request("PROPFIND", "", headers={"Depth": "0"})
        ok = antwort.status_code in (200, 207)
        return {"ok": ok, "detail": f"HTTP {antwort.status_code}"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    finally:
        client.close()


@router.get("/setup/5")
def setup_schritt5(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    return templates.TemplateResponse("setup_5_import.html", {"request": request})


def _archivio_pruefen(pfad: str) -> dict:
    if not pfad or not Path(pfad).is_file():
        return {"gefunden": False, "anzahl": 0}
    try:
        conn = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
        anzahl = conn.execute("SELECT COUNT(*) FROM signatur_quelle").fetchone()[0]
        conn.close()
        return {"gefunden": True, "anzahl": anzahl}
    except Exception:
        return {"gefunden": True, "anzahl": 0}


@router.get("/setup/6")
def setup_schritt6_form(request: Request, gespeichert: str = ""):
    if (r := _nur_lokal(request)) is not None:
        return r
    pfad = settings.get("archivio.signatur_db_path", "") or ""
    return templates.TemplateResponse("setup_6_archivio.html", {
        "request": request,
        "gespeichert": bool(gespeichert),
        "archivio_signatur_db_path": pfad,
        "archivio_min_mails": settings.get("archivio.min_mails", 2),
        "pruefung": _archivio_pruefen(pfad),
    })


@router.post("/setup/6")
async def setup_schritt6_speichern(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    form = await request.form()
    signatur_db_path = (form.get("archivio_signatur_db_path") or "").strip()
    try:
        min_mails = int(form.get("archivio_min_mails") or 2)
    except ValueError:
        min_mails = 2
    settings.save({"archivio": {"signatur_db_path": signatur_db_path, "min_mails": min_mails}})
    return RedirectResponse(url="/setup/6?gespeichert=1", status_code=303)


@router.get("/setup/7")
def setup_schritt7(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    return templates.TemplateResponse("setup_7_fertig.html", {"request": request})


@router.post("/setup/7")
def setup_schritt7_abschliessen(request: Request):
    if (r := _nur_lokal(request)) is not None:
        return r
    settings.save({"setup": {"completed": True}})
    return RedirectResponse(url="/kontakte", status_code=303)
