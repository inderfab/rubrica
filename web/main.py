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
import kontakte_app_intake
import mail_intake
from db import connection
from web.contacts import router as contacts_router
from web.folders import router as folders_router
from web.imports import router as imports_router
from web.export import router as export_router
from web.archivio import router as archivio_router
from web.vorschlaege import router as vorschlaege_router
from web.anleitung import router as anleitung_router
from web.settings import router as settings_router
from web.setup import router as setup_router
from web.shared import _setup_erforderlich

log = logging.getLogger(__name__)

# Bewusst zwei verschiedene Takte im selben Thread:
# - Kontakte.app haengt an der eigenen Radicale-Instanz auf Loopback. Bei bis zu 20
#   verbundenen Geraeten sollen dort angelegte Kontakte und verschobene Ordner-
#   Zuordnungen zeitnah in Rubrica ankommen, nicht erst am naechsten Tag.
# - Der Mail-Eingang geht an ein fremdes IMAP-Postfach ueber das Internet. Das alle
#   fuenf Minuten anzufassen waere unnoetige Last und koennte in Verbindungslimits
#   laufen - hier bleibt es beim Tagesrhythmus.
_KONTAKTE_APP_INTERVALL = 5 * 60
_MAIL_INTERVALL = 24 * 60 * 60


def _vorschlaege_ueberwachung():
    """Hintergrund-Ueberwachung beider Erfassungsquellen - zusaetzlich zum manuellen
    "Jetzt pruefen"-Knopf auf der Vorschlaege-Seite. Kurze Anfangswartezeit, damit der
    Server zuerst vollstaendig hochgefahren ist.

    Der Ordner-Abgleich hier ist die Absicherung fuer den Normalfall, dass niemand den
    betroffenen Ordner in Rubrica anfasst; gegen Datenverlust schuetzt bereits
    push_projekt selbst (Lesen vor Schreiben, siehe sync/radicale.py)."""
    time.sleep(60)
    letzte_mail_pruefung = None
    while True:
        jetzt = time.monotonic()
        if letzte_mail_pruefung is None or jetzt - letzte_mail_pruefung >= _MAIL_INTERVALL:
            letzte_mail_pruefung = jetzt
            conn = connection.get_connection()
            try:
                if mail_intake.konfiguriert():
                    mail_intake.pruefe_mail_eingang(conn)
            except Exception:
                log.exception("Taeglicher Mail-Eingang-Check fehlgeschlagen")
            finally:
                conn.close()

        conn = connection.get_connection()
        try:
            if kontakte_app_intake.konfiguriert():
                kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(conn)
        except Exception:
            log.exception("Kontakte.app-Check fehlgeschlagen")
        finally:
            conn.close()

        # Getrennte Verbindung und eigener Fehlerfang: der Ordner-Abgleich soll auch
        # dann laufen, wenn der Neuzugaenge-Check oben gescheitert ist.
        conn = connection.get_connection()
        try:
            if kontakte_app_intake.konfiguriert():
                kontakte_app_intake.pruefe_ordner_mitgliedschaften(conn)
        except Exception:
            log.exception("Ordner-Mitgliedschafts-Abgleich fehlgeschlagen")
        finally:
            conn.close()

        conn = connection.get_connection()
        try:
            if kontakte_app_intake.konfiguriert():
                kontakte_app_intake.pruefe_kontakt_aenderungen(conn)
        except Exception:
            log.exception("Aenderungserkennung fehlgeschlagen")
        finally:
            conn.close()

        time.sleep(_KONTAKTE_APP_INTERVALL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection.init_schema()
    threading.Thread(target=_vorschlaege_ueberwachung, daemon=True).start()
    yield


app = FastAPI(title="Rubrica", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="web/static"), name="static")
app.include_router(contacts_router)
app.include_router(folders_router)
app.include_router(imports_router)
app.include_router(export_router)
app.include_router(archivio_router)
app.include_router(vorschlaege_router)
app.include_router(anleitung_router)
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
