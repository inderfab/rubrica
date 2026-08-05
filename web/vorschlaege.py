"""Review-Seite fuer Vorschlaege aus zwei Quellen: dem Mail-Eingang (siehe
mail_intake.py) und direkt in Kontakte.app angelegten Kontakten/Ordnern (siehe
kontakte_app_intake.py). Im Gegensatz zu Import-/Archivio-Vorschlaegen bleiben diese
bewusst auf 'offen' stehen, bis sie hier manuell bestaetigt oder abgelehnt werden -
ein von aussen erreichbares Postfach bzw. eine direkt in Kontakte.app angelegte
vCard sind ein weniger vertrauenswuerdiger Kanal als Import/Archivio, die vom
Buero-Rechner selbst ausgehen. Ein Vorschlag mit rohdaten.typ == "ordner" ist ein
in Kontakte.app neu angelegter Ordner statt eines Kontakts (siehe
kontakte_app_intake.bestaetige_ordner_vorschlag)."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

import kontakte_app_intake
import mail_intake
from db import queries
from db.connection import get_connection
from sync import radicale
from web.contacts import (
    _email_typ_optionen,
    _funktion_optionen,
    _parse_kontakt_form,
    _telefon_typ_optionen,
    _validiere_pflichtfelder,
)
from web.shared import templates

router = APIRouter()

_QUELLEN = ["mail", "kontakte_app"]


def _fremde_vcard_entfernen(vorschlag: dict) -> None:
    """Entfernt bei quelle='kontakte_app' die urspruengliche, direkt in Kontakte.app
    angelegte vCard aus Radicale. Noetig in BEIDEN Ausgaengen:

    - beim Bestaetigen, weil Rubrica den Eintrag danach unter eigener UID
      (kontakt-N.vcf bzw. projekt-N.vcf) pusht - sonst staende er doppelt in
      Kontakte.app;
    - beim Ablehnen, weil die vCard sonst als Karteileiche im gemeinsamen
      Adressbuch liegen bliebe: auf allen verbundenen Geraeten sichtbar, von
      Rubrica nicht verwaltet, in keinem Export enthalten - und nie wieder
      angeboten, da der Dublettenschutz (queries.vorschlag_existiert_fuer_message_id)
      nur nach der message_id fragt und den Status bewusst ignoriert.

    Fuer quelle='mail' gibt es keine vCard auf Radicale, der Aufruf ist dort ein
    No-op."""
    if vorschlag["quelle"] != "kontakte_app":
        return
    name = vorschlag["rohdaten"].get("kontakte_app_vcf_name")
    if name:
        kontakte_app_intake.loesche_fremde_vcard(name)


@router.get("/vorschlaege")
def vorschlaege_seite(request: Request, meldung: str = ""):
    conn = get_connection()
    try:
        vorschlaege = queries.list_vorschlaege(conn, status="offen", quelle=_QUELLEN)
    finally:
        conn.close()
    return templates.TemplateResponse("vorschlaege.html", {
        "request": request, "vorschlaege": vorschlaege, "meldung": meldung,
    })


@router.post("/vorschlaege/pruefen")
def vorschlaege_pruefen():
    conn = get_connection()
    try:
        text = f"{mail_intake.pruefe_und_beschreibe(conn)} {kontakte_app_intake.pruefe_und_beschreibe(conn)}"
    finally:
        conn.close()
    return RedirectResponse(url=f"/vorschlaege?meldung={quote(text)}", status_code=303)


@router.post("/vorschlaege/{vorschlag_id}/uebernehmen")
def vorschlag_uebernehmen(vorschlag_id: int):
    conn = get_connection()
    try:
        vorschlag = queries.get_vorschlag(conn, vorschlag_id)
        if vorschlag and vorschlag["rohdaten"].get("typ") == "ordner":
            projekt_id = kontakte_app_intake.bestaetige_ordner_vorschlag(conn, vorschlag)
            queries.set_vorschlag_status(conn, vorschlag_id, "bestaetigt")
            radicale.push_projekt(conn, projekt_id)
            _fremde_vcard_entfernen(vorschlag)
        else:
            ordner_ids = vorschlag["rohdaten"].get("erkannte_ordner_ids") if vorschlag else None
            kontakt_id = queries.bestaetige_vorschlag(conn, vorschlag_id, ordner_ids=ordner_ids)
            radicale.push_kontakt_mit_ordnern(conn, kontakt_id)
            if vorschlag:
                _fremde_vcard_entfernen(vorschlag)
    finally:
        conn.close()
    return RedirectResponse(url="/vorschlaege", status_code=303)


@router.post("/vorschlaege/{vorschlag_id}/ablehnen")
def vorschlag_ablehnen(vorschlag_id: int):
    """Ablehnen entfernt bei quelle='kontakte_app' zusaetzlich die urspruengliche
    vCard aus dem gemeinsamen Adressbuch - der Eintrag verschwindet damit auch in
    Kontakte.app auf allen Geraeten. Ohne das bliebe er als Karteileiche liegen
    (siehe _fremde_vcard_entfernen). Wer den Kontakt privat behalten will, muss
    ihn vorher in Kontakte.app in ein eigenes Konto verschieben - darauf weist
    die Rueckfrage im Formular hin (vorschlaege.html)."""
    conn = get_connection()
    try:
        vorschlag = queries.get_vorschlag(conn, vorschlag_id)
        queries.set_vorschlag_status(conn, vorschlag_id, "abgelehnt")
    finally:
        conn.close()
    if vorschlag:
        _fremde_vcard_entfernen(vorschlag)
    return RedirectResponse(url="/vorschlaege", status_code=303)


@router.get("/vorschlaege/{vorschlag_id}/bearbeiten-flyover")
def vorschlag_bearbeiten_flyover(request: Request, vorschlag_id: int):
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
    erkannte_ordner_ids = set(daten.get("erkannte_ordner_ids", []))
    pseudo_kontakt = dict(daten)
    pseudo_kontakt["projekte"] = [
        {"id": o["id"]} for o in ordner if o["name"] in gruppen_namen or o["id"] in erkannte_ordner_ids
    ]

    return templates.TemplateResponse("archivio_bearbeiten_modal.html", {
        "request": request, "kontakt": pseudo_kontakt, "ordner": ordner, "funktionen": funktionen,
        "telefon_typen": telefon_typen, "email_typen": email_typen,
        "action": f"/vorschlaege/{vorschlag_id}/uebernehmen-bearbeitet",
        "modal": True, "zurueck_ordner_id": "", "hx_target": "mail-modal-inhalt",
    })


@router.post("/vorschlaege/{vorschlag_id}/uebernehmen-bearbeitet")
async def vorschlag_uebernehmen_bearbeitet(request: Request, vorschlag_id: int):
    """Wird per htmx abgeschickt (siehe hx_target im Bearbeiten-Formular): bei
    fehlenden Pflichtfeldern wird das Modal mit rot markierten Feldern neu
    eingeschwenkt statt die Seite zu verlassen; bei Erfolg sorgt HX-Redirect fuer
    einen echten Seitenwechsel. Ordner_ids werden hier direkt (statt ueber den
    Namens-Umweg gruppen_als_ordner) an bestaetige_vorschlag durchgereicht - alle
    im Formular angebotenen Ordner existieren bereits, es muss also nie ein neuer
    Ordner anhand eines Namens angelegt werden."""
    form = await request.form()
    daten = _parse_kontakt_form(form)
    ordner_ids = {int(o) for o in form.getlist("ordner_ids")}

    conn = get_connection()
    try:
        fehlende_felder = _validiere_pflichtfelder(daten, list(ordner_ids))
        if fehlende_felder:
            ordner = queries.list_projekte(conn)
            pseudo_kontakt = dict(daten)
            pseudo_kontakt["projekte"] = [{"id": oid} for oid in ordner_ids]
            return templates.TemplateResponse("archivio_bearbeiten_modal.html", {
                "request": request, "kontakt": pseudo_kontakt, "ordner": ordner,
                "funktionen": _funktion_optionen(conn),
                "telefon_typen": _telefon_typ_optionen(conn), "email_typen": _email_typ_optionen(conn),
                "action": f"/vorschlaege/{vorschlag_id}/uebernehmen-bearbeitet",
                "modal": True, "zurueck_ordner_id": "", "hx_target": "mail-modal-inhalt",
                "fehlende_felder": fehlende_felder,
            })
        vorschlag = queries.get_vorschlag(conn, vorschlag_id)
        queries.update_vorschlag_rohdaten(conn, vorschlag_id, daten)
        kontakt_id = queries.bestaetige_vorschlag(conn, vorschlag_id, ordner_ids=list(ordner_ids))
        radicale.push_kontakt_mit_ordnern(conn, kontakt_id)
        if vorschlag:
            _fremde_vcard_entfernen(vorschlag)
    finally:
        conn.close()
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=200, headers={"HX-Redirect": "/vorschlaege"})
    return RedirectResponse(url="/vorschlaege", status_code=303)
