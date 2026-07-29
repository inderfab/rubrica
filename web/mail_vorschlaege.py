"""Review-Seite fuer Kontaktvorschlaege aus dem Mail-Eingang (siehe mail_intake.py).
Im Gegensatz zu Import-/Archivio-Vorschlaegen bleiben diese bewusst auf 'offen'
stehen, bis sie hier manuell bestaetigt oder abgelehnt werden - ein von aussen
erreichbares Postfach ist ein weniger vertrauenswuerdiger Kanal als Import/Archivio,
die vom Buero-Rechner selbst ausgehen."""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from db import queries
from db.connection import get_connection
from sync import radicale
from web.contacts import _email_typ_optionen, _funktion_optionen, _parse_kontakt_form, _telefon_typ_optionen
from web.shared import templates

router = APIRouter()


@router.get("/mail-vorschlaege")
def mail_vorschlaege_seite(request: Request):
    conn = get_connection()
    try:
        vorschlaege = queries.list_vorschlaege(conn, status="offen", quelle="mail")
    finally:
        conn.close()
    return templates.TemplateResponse("mail_vorschlaege.html", {
        "request": request, "vorschlaege": vorschlaege,
    })


@router.post("/mail-vorschlaege/{vorschlag_id}/uebernehmen")
def mail_vorschlag_uebernehmen(vorschlag_id: int):
    conn = get_connection()
    try:
        kontakt_id = queries.bestaetige_vorschlag(conn, vorschlag_id)
        radicale.push_kontakt_mit_ordnern(conn, kontakt_id)
    finally:
        conn.close()
    return RedirectResponse(url="/mail-vorschlaege", status_code=303)


@router.post("/mail-vorschlaege/{vorschlag_id}/ablehnen")
def mail_vorschlag_ablehnen(vorschlag_id: int):
    conn = get_connection()
    try:
        queries.set_vorschlag_status(conn, vorschlag_id, "abgelehnt")
    finally:
        conn.close()
    return RedirectResponse(url="/mail-vorschlaege", status_code=303)


@router.get("/mail-vorschlaege/{vorschlag_id}/bearbeiten-flyover")
def mail_vorschlag_bearbeiten_flyover(request: Request, vorschlag_id: int):
    """Identisches Bearbeiten-Formular wie beim Kontakt-Bearbeiten/Archivio-Import
    (siehe archivio_bearbeiten_modal.html) - "kontakt" ist hier ein aus den
    gespeicherten rohdaten nachgebautes Pseudo-Kontakt-Dict."""
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

    daten = vorschlag["rohdaten"]
    gruppen_namen = set(daten.get("gruppen_als_ordner", []))
    pseudo_kontakt = dict(daten)
    pseudo_kontakt["projekte"] = [{"id": o["id"]} for o in ordner if o["name"] in gruppen_namen]

    return templates.TemplateResponse("archivio_bearbeiten_modal.html", {
        "request": request, "kontakt": pseudo_kontakt, "ordner": ordner, "funktionen": funktionen,
        "telefon_typen": telefon_typen, "email_typen": email_typen,
        "action": f"/mail-vorschlaege/{vorschlag_id}/uebernehmen-bearbeitet",
        "modal": True, "zurueck_ordner_id": "",
    })


@router.post("/mail-vorschlaege/{vorschlag_id}/uebernehmen-bearbeitet")
async def mail_vorschlag_uebernehmen_bearbeitet(request: Request, vorschlag_id: int):
    form = await request.form()
    daten = _parse_kontakt_form(form)
    ordner_ids = {int(o) for o in form.getlist("ordner_ids")}

    conn = get_connection()
    try:
        ordner = queries.list_projekte(conn)
        daten["gruppen_als_ordner"] = [o["name"] for o in ordner if o["id"] in ordner_ids]
        queries.update_vorschlag_rohdaten(conn, vorschlag_id, daten)
        kontakt_id = queries.bestaetige_vorschlag(conn, vorschlag_id)
        radicale.push_kontakt_mit_ordnern(conn, kontakt_id)
    finally:
        conn.close()
    return RedirectResponse(url="/mail-vorschlaege", status_code=303)
