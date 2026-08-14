from __future__ import annotations

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import RedirectResponse

from db import queries
from db.connection import get_connection
from importer.vcard import importiere
from sync import radicale
from web import import_status
from web.shared import _ist_lokale_maschine, templates

router = APIRouter()


def _ist_lokal(request: Request) -> bool:
    """Der Kontakte.app-Import liest die Kontakte.app auf der Maschine, auf der
    Rubrica laeuft (osascript, serverseitig) - nicht auf dem Rechner der/des
    Zugreifenden. Ueber das Buero-LAN wuerde das versehentlich das Adressbuch
    des Servers statt des eigenen importieren, daher wie im Setup-Assistenten
    nur auf dem Server-Rechner selbst anbieten."""
    return _ist_lokale_maschine(request)


@router.get("/import")
def import_form(request: Request):
    return templates.TemplateResponse("import_form.html", {
        "request": request, "kontakte_app_lokal": _ist_lokal(request),
    })


@router.post("/import/kontakte-app")
def import_kontakte_app(request: Request):
    if not _ist_lokal(request):
        return {"gestartet": False, "detail": "Nur direkt auf diesem Rechner möglich."}
    return {"gestartet": import_status.starten()}


@router.get("/import/kontakte-app/status")
def import_kontakte_app_status(request: Request):
    if not _ist_lokal(request):
        return {"laeuft": False}
    return import_status.status()


@router.get("/import/zusammengefuehrte-duplikate")
def import_zusammengefuehrte_duplikate(request: Request):
    """Zeigt alle Import-Vorschlaege, die als Dublette in einen bestehenden Kontakt
    gemergt statt neu angelegt wurden - Nachvollziehbarkeit fuer den Nutzer, ob die
    Differenz zwischen "gefunden" und "importiert" wirklich echte Dubletten sind."""
    conn = get_connection()
    try:
        zusammenfuehrungen = queries.list_import_zusammenfuehrungen(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("import_duplikate.html", {
        "request": request, "zusammenfuehrungen": zusammenfuehrungen,
    })


@router.post("/import")
async def import_hochladen(request: Request, dateien: list[UploadFile]):
    """Apple-Gruppen werden immer versucht zu uebernehmen (frueher eine
    Checkbox, die praktisch wirkungslos war - Gruppenzugehoerigkeit steht nur
    in vCards drin, wenn eine ganze Gruppe statt einzelner Kontakte exportiert
    wurde; ohne solche Daten passiert einfach nichts). Kontakte werden direkt
    angelegt bzw. gemergt (keine Review-Queue mehr) - Korrekturen erfolgen
    danach direkt am Kontakt."""
    form = await request.form()
    nie_zusammenfuehren = form.get("nie_zusammenfuehren") is not None

    conn = get_connection()
    try:
        vorher = {r["id"] for r in conn.execute("SELECT id FROM kontakte")}
        kontakt_ids = []
        for datei in dateien:
            inhalt = (await datei.read()).decode("utf-8", errors="replace")
            kontakt_ids.extend(importiere(conn, inhalt, nie_zusammenfuehren=nie_zusammenfuehren))
        # Eine Verbindung fuer den ganzen Batch wiederverwenden statt pro Kontakt
        # eine eigene TLS-Verbindung aufzubauen (siehe sync.radicale.sync_alle).
        client = radicale._client()
        try:
            for kontakt_id in set(kontakt_ids):
                radicale.push_kontakt_mit_ordnern(conn, kontakt_id, client=client)
        finally:
            if client is not None:
                client.close()
        # Rueckmeldung statt stiller Weiterleitung (Nutzer-Meldung: "es laedt und
        # springt dann zu den kontakten. die kontakte sind aber dort nicht
        # ersichtlich"). Wer nicht sieht, wie viele Karten in einen bestehenden
        # Kontakt gewandert sind, sucht sie vergeblich in der Liste.
        neue = [k for k in dict.fromkeys(kontakt_ids) if k not in vorher]
        zusammengefuehrt = [k for k in dict.fromkeys(kontakt_ids) if k in vorher]
        ergebnis = {
            "neu": [queries.get_kontakt(conn, k) for k in neue],
            "zusammengefuehrt": [queries.get_kontakt(conn, k) for k in zusammengefuehrt],
            "nie_zusammenfuehren": nie_zusammenfuehren,
        }
        return templates.TemplateResponse("import_ergebnis.html",
                                           {"request": request, **ergebnis})
    finally:
        conn.close()
