from __future__ import annotations

from typing import List

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from db import queries
from db.connection import get_connection
from sync import radicale
from web.contacts import (
    FELDER_MEHRFACHBEARBEITUNG,
    _email_typ_optionen,
    _funktion_optionen,
    _parse_kontakt_form,
    _telefon_typ_optionen,
)
from web.shared import templates

router = APIRouter()


def _push_nach_bestaetigung(conn, kontakt_id: int) -> None:
    radicale.push_kontakt(conn, kontakt_id)
    for p in queries.get_kontakt(conn, kontakt_id)["projekte"]:
        radicale.push_projekt(conn, p["id"])


@router.get("/review")
def review_liste(request: Request):
    conn = get_connection()
    try:
        vorschlaege = queries.list_vorschlaege(conn, status="offen")
        ordner = queries.list_projekte(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("review_queue.html", {
        "request": request, "vorschlaege": vorschlaege, "ordner": ordner,
    })


@router.post("/review/{vorschlag_id}/bestaetigen")
async def review_bestaetigen(vorschlag_id: int, request: Request):
    form = await request.form()
    ordner_ids = [int(i) for i in form.getlist("ordner_ids")]
    conn = get_connection()
    try:
        kontakt_id = queries.bestaetige_vorschlag(conn, vorschlag_id, ordner_ids=ordner_ids or None)
        _push_nach_bestaetigung(conn, kontakt_id)
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.post("/review/{vorschlag_id}/ablehnen")
def review_ablehnen(vorschlag_id: int):
    conn = get_connection()
    try:
        queries.set_vorschlag_status(conn, vorschlag_id, "abgelehnt")
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.get("/review/{vorschlag_id}/bearbeiten-flyover")
def review_bearbeiten_flyover(request: Request, vorschlag_id: int):
    """Vollstaendiges Bearbeiten EINES Vorschlags vor der Bestaetigung - bewusst
    dasselbe Formular/Template wie beim Kontakt-Bearbeiten (_kontakt_bearbeiten_form.html),
    inklusive Telefon-/E-Mail-/Adress-/URL-Arrays (im Gegensatz zum Sammel-Bearbeiten
    mehrerer Vorschlaege, das aus denselben Gruenden wie bei Kontakten nur Scalar-Felder
    unterstuetzt)."""
    conn = get_connection()
    try:
        vorschlag = queries.get_vorschlag(conn, vorschlag_id)
        ordner = queries.list_projekte(conn)
        funktionen = _funktion_optionen(conn)
        telefon_typen = _telefon_typ_optionen(conn)
        email_typen = _email_typ_optionen(conn)
    finally:
        conn.close()
    if vorschlag is None:
        return Response(status_code=404)

    rohdaten = vorschlag["rohdaten"]
    gruppen_namen = set(rohdaten.get("gruppen_als_ordner", []))
    # _kontakt_bearbeiten_form.html erwartet "kontakt.projekte" (Liste von Dicts mit
    # "id") fuer die Ordner-Checkliste - rohdaten hat stattdessen NAMEN in
    # gruppen_als_ordner (aus Apple-Gruppen-Erkennung). Gleiche Form wie bei einem
    # echten Kontakt nachbauen, damit das Template unveraendert wiederverwendbar ist.
    pseudo_kontakt = dict(rohdaten)
    pseudo_kontakt["projekte"] = [{"id": o["id"]} for o in ordner if o["name"] in gruppen_namen]

    return templates.TemplateResponse("review_bearbeiten_modal.html", {
        "request": request, "kontakt": pseudo_kontakt, "ordner": ordner, "funktionen": funktionen,
        "telefon_typen": telefon_typen, "email_typen": email_typen,
        "action": f"/review/{vorschlag_id}/bearbeiten-vollstaendig", "modal": True,
        "zurueck_ordner_id": "",
    })


@router.post("/review/{vorschlag_id}/bearbeiten-vollstaendig")
async def review_bearbeiten_speichern_vollstaendig(request: Request, vorschlag_id: int):
    """Speichert die vollstaendig editierten Werte (inkl. Telefon/E-Mail/Adresse/URL)
    direkt ins rohdaten-JSON zurueck - der Vorschlag bleibt bis zur Bestaetigung
    unangetastet in der Review-Queue."""
    form = await request.form()
    daten = _parse_kontakt_form(form)
    ordner_ids = {int(o) for o in form.getlist("ordner_ids")}

    conn = get_connection()
    try:
        ordner = queries.list_projekte(conn)
        daten["gruppen_als_ordner"] = [o["name"] for o in ordner if o["id"] in ordner_ids]
        queries.update_vorschlag_rohdaten(conn, vorschlag_id, daten)
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.post("/review/bulk-bestaetigen")
async def review_bulk_bestaetigen(request: Request):
    """Bestaetigt entweder gezielt die uebergebenen ids ("Nur ausgewaehlte bestaetigen") oder,
    falls keine ids mitgeschickt wurden, alle aktuell offenen Vorschlaege ("Alle bestaetigen")."""
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids")]
    conn = get_connection()
    try:
        zu_bestaetigen = ids if ids else [v["id"] for v in queries.list_vorschlaege(conn, status="offen")]
        for vorschlag_id in zu_bestaetigen:
            kontakt_id = queries.bestaetige_vorschlag(conn, vorschlag_id)
            _push_nach_bestaetigung(conn, kontakt_id)
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.post("/review/bulk-ablehnen")
async def review_bulk_ablehnen(request: Request):
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids")]
    conn = get_connection()
    try:
        for vorschlag_id in ids:
            queries.set_vorschlag_status(conn, vorschlag_id, "abgelehnt")
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.get("/review/bulk-bearbeiten-flyover")
def review_bulk_bearbeiten_flyover(request: Request, ids: List[int] = Query(...)):
    """Sammel-Bearbeiten fuer einen oder mehrere Vorschlaege vor der Bestaetigung - gleiches
    gemischt/Prinzip wie kontakte_bulk_bearbeiten_flyover: nur Scalar-Felder, Arrays (Telefon/
    E-Mail/Adresse) bleiben unangetastet, da sie erst beim Bestaetigen echte Kontaktdaten werden."""
    conn = get_connection()
    try:
        vorschlaege = [queries.get_vorschlag(conn, vid) for vid in ids]
        funktionen = _funktion_optionen(conn)
    finally:
        conn.close()

    felder = {}
    for feld in FELDER_MEHRFACHBEARBEITUNG:
        werte = {v["rohdaten"].get(feld, "") for v in vorschlaege}
        if len(werte) == 1:
            felder[feld] = {"wert": werte.pop(), "gemischt": False}
        else:
            felder[feld] = {"wert": "", "gemischt": True}

    return templates.TemplateResponse("review_bulk_bearbeiten_modal.html", {
        "request": request, "vorschlaege": vorschlaege, "ids": ids, "felder": felder,
        "funktionen": funktionen,
    })


@router.post("/review/bulk-bearbeiten")
async def review_bulk_bearbeiten_speichern(request: Request):
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids")]

    updates = {}
    for feld in FELDER_MEHRFACHBEARBEITUNG:
        war_gemischt = form.get(f"{feld}__gemischt", "") == "1"
        wert = form.get(feld, "").strip()
        if war_gemischt and not wert:
            continue
        updates[feld] = wert

    conn = get_connection()
    try:
        if updates:
            for vorschlag_id in ids:
                queries.update_vorschlag_rohdaten(conn, vorschlag_id, updates)
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)
