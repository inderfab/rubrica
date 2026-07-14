from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import backup
from db import connection
from web.contacts import router as contacts_router
from web.folders import router as folders_router
from web.imports import router as imports_router
from web.export import router as export_router
from web.archivio import router as archivio_router
from web.settings import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection.init_schema()
    yield


app = FastAPI(title="Rubrica", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="web/static"), name="static")
app.include_router(contacts_router)
app.include_router(folders_router)
app.include_router(imports_router)
app.include_router(export_router)
app.include_router(archivio_router)
app.include_router(settings_router)


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
    return RedirectResponse(url="/kontakte")
