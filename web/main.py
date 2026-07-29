from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import backup
import mail_intake
from db import connection
from web.contacts import router as contacts_router
from web.folders import router as folders_router
from web.imports import router as imports_router
from web.export import router as export_router
from web.archivio import router as archivio_router
from web.mail_vorschlaege import router as mail_vorschlaege_router
from web.settings import router as settings_router
from web.setup import router as setup_router
from web.shared import _setup_erforderlich

log = logging.getLogger(__name__)

_MAIL_PRUEF_INTERVALL = 24 * 60 * 60


def _mail_ueberwachung():
    """Prueft 1x taeglich das Mail-Eingang-Postfach im Hintergrund (siehe
    mail_intake.py) - zusaetzlich zum manuellen "Jetzt pruefen"-Knopf in den
    Einstellungen. Kurze Anfangswartezeit, damit der Server zuerst vollstaendig
    hochgefahren ist."""
    time.sleep(60)
    while True:
        try:
            if mail_intake.konfiguriert():
                conn = connection.get_connection()
                try:
                    mail_intake.pruefe_mail_eingang(conn)
                finally:
                    conn.close()
        except Exception:
            log.exception("Taeglicher Mail-Eingang-Check fehlgeschlagen")
        time.sleep(_MAIL_PRUEF_INTERVALL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection.init_schema()
    threading.Thread(target=_mail_ueberwachung, daemon=True).start()
    yield


app = FastAPI(title="Rubrica", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="web/static"), name="static")
app.include_router(contacts_router)
app.include_router(folders_router)
app.include_router(imports_router)
app.include_router(export_router)
app.include_router(archivio_router)
app.include_router(mail_vorschlaege_router)
app.include_router(settings_router)
app.include_router(setup_router)


@app.middleware("http")
async def backup_nach_aenderung(request: Request, call_next):
    """Loest nach jeder erfolgreichen aendernden Anfrage (POST - Kontakt/Ordner
    anlegen, bearbeiten, loeschen, Vorschlag bestaetigen usw.) ein Backup aus,
    falls in den Einstellungen ein Backup-Pfad hinterlegt ist. Im Threadpool,
    damit ein langsamer Zielpfad (z. B. NAS) die Event-Loop nicht blockiert."""
    response = await call_next(request)
    if request.method == "POST" and response.status_code < 400:
        await run_in_threadpool(backup.sichern_falls_konfiguriert)
    return response


@app.get("/")
def root():
    if _setup_erforderlich():
        return RedirectResponse(url="/setup/1")
    return RedirectResponse(url="/kontakte")
