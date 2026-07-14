"""Phase 4: Vorschau + Uebernahme von Archivio-Kontaktvorschlaegen aus der Archivio-
Signatur-DB (Tabelle signatur_quelle). Vorschau liest (und markiert Status, siehe
archivio_bridge.anbindung), Uebernahme schreibt in die Review-Queue
(vorschlaege, quelle='archivio') - nie direkt in kontakte."""
from __future__ import annotations

from typing import List
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import RedirectResponse

from archivio_bridge.anbindung import hole_kandidaten, liste_postfaecher, markiere_status
from config import settings
from db import queries
from db.connection import get_connection
from web.contacts import (
    FELDER_MEHRFACHBEARBEITUNG,
    _email_typ_optionen,
    _funktion_optionen,
    _parse_kontakt_form,
    _telefon_typ_optionen,
)
from web.shared import templates

router = APIRouter()


def _signatur_db_pfad() -> str:
    return settings.get("archivio.signatur_db_path", "") or ""


def _hole_kandidaten_oder_leer(conn, postfaecher: List[str]):
    db_pfad = _signatur_db_pfad()
    if not db_pfad:
        return [], "Keine Archivio-Signatur-Datenbank konfiguriert (archivio.signatur_db_path in den Einstellungen)."
    min_mails = settings.get("archivio.min_mails", 2)
    try:
        return hole_kandidaten(db_pfad, conn, min_mails=min_mails, postfaecher=postfaecher or None), ""
    except Exception as exc:
        return [], f"Archivio-Signatur-Datenbank nicht lesbar: {type(exc).__name__}"


def _postfaecher_oder_leer() -> list:
    db_pfad = _signatur_db_pfad()
    if not db_pfad:
        return []
    try:
        return liste_postfaecher(db_pfad)
    except Exception:
        return []


def _kandidat_uebernehmen(conn, daten: dict) -> None:
    daten.pop("anzahl_mails", None)
    absender_email = daten.pop("absender_email", None)
    queries.create_vorschlag(conn, daten, quelle="archivio")
    if absender_email:
        markiere_status(_signatur_db_pfad(), absender_email, "uebernommen")


def _kandidat_ablehnen(conn, daten: dict) -> None:
    daten.pop("anzahl_mails", None)
    absender_email = daten.pop("absender_email", None)
    vorschlag_id = queries.create_vorschlag(conn, daten, quelle="archivio")
    queries.set_vorschlag_status(conn, vorschlag_id, "abgelehnt")
    if absender_email:
        markiere_status(_signatur_db_pfad(), absender_email, "abgelehnt")


@router.get("/archivio-import")
def archivio_import_seite(request: Request, postfaecher: List[str] = Query(default=[])):
    conn = get_connection()
    try:
        kandidaten, fehler = _hole_kandidaten_oder_leer(conn, postfaecher)
        alle_postfaecher = _postfaecher_oder_leer()
        ordner = queries.list_projekte(conn)
        zuordnungen = queries.postfach_zuordnungen(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("archivio_import.html", {
        "request": request, "kandidaten": kandidaten, "fehler": fehler,
        "alle_postfaecher": alle_postfaecher, "ausgewaehlte_postfaecher": set(postfaecher),
        "ordner": ordner, "zuordnungen": zuordnungen,
    })


@router.post("/archivio-import/postfach-zuordnen")
async def archivio_postfach_zuordnen(request: Request):
    form = await request.form()
    postfach = form.get("postfach", "").strip()
    projekt_id_roh = form.get("projekt_id", "").strip()
    projekt_id = int(projekt_id_roh) if projekt_id_roh else None
    conn = get_connection()
    try:
        queries.postfach_zuordnen(conn, postfach, projekt_id)
    finally:
        conn.close()
    return RedirectResponse(url="/archivio-import", status_code=303)


@router.post("/archivio-import/uebernehmen")
async def archivio_uebernehmen(request: Request):
    """Uebernimmt ALLE aktuell angezeigten Kandidaten auf einmal in die Review-Queue."""
    form = await request.form()
    postfaecher = form.getlist("postfaecher")
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        for daten in kandidaten:
            _kandidat_uebernehmen(conn, daten)
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.post("/archivio-import/uebernehmen-einzeln")
async def archivio_uebernehmen_einzeln(request: Request, email: str = Form(...)):
    """Uebernimmt genau EINEN Kandidaten (identifiziert per E-Mail-Adresse -
    die ist durch die strenge Vollstaendigkeitspruefung in hole_kandidaten immer
    vorhanden) als offenen Vorschlag in die Review-Queue."""
    form = await request.form()
    postfaecher = form.getlist("postfaecher")
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        for daten in kandidaten:
            if daten["emails"] and daten["emails"][0]["email"].lower() == email.lower():
                _kandidat_uebernehmen(conn, daten)
                break
    finally:
        conn.close()
    return RedirectResponse(url="/archivio-import", status_code=303)


@router.post("/archivio-import/uebernehmen-ausgewaehlte")
async def archivio_uebernehmen_ausgewaehlte(request: Request):
    """Uebernimmt mehrere ausgewaehlte Kandidaten auf einmal (Sammel-Leiste,
    gleiches Mehrfachauswahl-Prinzip wie bei Kontakten/Review-Queue)."""
    form = await request.form()
    postfaecher = form.getlist("postfaecher")
    emails = {e.lower() for e in form.getlist("emails")}
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        for daten in kandidaten:
            if daten["emails"] and daten["emails"][0]["email"].lower() in emails:
                _kandidat_uebernehmen(conn, daten)
    finally:
        conn.close()
    return RedirectResponse(url="/archivio-import", status_code=303)


@router.get("/archivio-import/bulk-bearbeiten-flyover")
def archivio_bulk_bearbeiten_flyover(
    request: Request, emails: List[str] = Query(...), postfaecher: List[str] = Query(default=[])
):
    """Sammel-Bearbeiten fuer mehrere ausgewaehlte Archivio-Kandidaten - gleiches
    gemischt-Prinzip wie review_bulk_bearbeiten_flyover: nur Scalar-Felder, Arrays
    (Telefon/E-Mail/Adresse) bleiben unangetastet."""
    emails_lower = {e.lower() for e in emails}
    conn = get_connection()
    try:
        alle_kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        funktionen = _funktion_optionen(conn)
    finally:
        conn.close()
    kandidaten = [
        k for k in alle_kandidaten if k["emails"] and k["emails"][0]["email"].lower() in emails_lower
    ]

    felder = {}
    for feld in FELDER_MEHRFACHBEARBEITUNG:
        werte = {k.get(feld, "") for k in kandidaten}
        if len(werte) == 1:
            felder[feld] = {"wert": werte.pop(), "gemischt": False}
        else:
            felder[feld] = {"wert": "", "gemischt": True}

    return templates.TemplateResponse("archivio_bulk_bearbeiten_modal.html", {
        "request": request, "kandidaten": kandidaten, "emails": emails, "postfaecher": postfaecher,
        "felder": felder, "funktionen": funktionen,
    })


@router.post("/archivio-import/bulk-bearbeiten")
async def archivio_bulk_bearbeiten_speichern(request: Request):
    """Wendet die editierten Scalar-Werte auf die ausgewaehlten Kandidaten an und
    uebernimmt sie direkt in die Review-Queue - im Gegensatz zum Sammel-Bearbeiten
    in der Review-Queue selbst (dort bereits als Vorschlag persistiert) gibt es fuer
    Archivio-Kandidaten keinen Zwischenzustand zum Speichern-ohne-Bestaetigen: sie
    werden bei jeder Anfrage frisch aus der Archivio-DB berechnet."""
    form = await request.form()
    emails = {e.lower() for e in form.getlist("emails")}
    postfaecher = form.getlist("postfaecher")

    updates = {}
    for feld in FELDER_MEHRFACHBEARBEITUNG:
        war_gemischt = form.get(f"{feld}__gemischt", "") == "1"
        wert = form.get(feld, "").strip()
        if war_gemischt and not wert:
            continue
        updates[feld] = wert

    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        for daten in kandidaten:
            if daten["emails"] and daten["emails"][0]["email"].lower() in emails:
                daten.update(updates)
                _kandidat_uebernehmen(conn, daten)
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.get("/archivio-import/bearbeiten-flyover")
def archivio_bearbeiten_flyover(request: Request, email: str, postfaecher: List[str] = Query(default=[])):
    """Zeigt dasselbe Bearbeiten-Formular wie beim Kontakt-Bearbeiten (alle Felder
    inkl. Telefon-/E-Mail-Kategorie-Auswahl, "+ Hinzufuegen"-Zeilen, Ordner-
    Checkliste) - haeufigster Korrekturfall laut Nutzer: die Signatur enthaelt
    eine Funktionsbezeichnung statt eines Namens."""
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        ordner = queries.list_projekte(conn)
        funktionen = _funktion_optionen(conn)
        telefon_typen = _telefon_typ_optionen(conn)
        email_typen = _email_typ_optionen(conn)
    finally:
        conn.close()
    daten = next(
        (k for k in kandidaten if k["emails"] and k["emails"][0]["email"].lower() == email.lower()), None
    )
    if daten is None:
        return Response(status_code=404)

    gruppen_namen = set(daten.get("gruppen_als_ordner", []))
    pseudo_kontakt = dict(daten)
    pseudo_kontakt["projekte"] = [{"id": o["id"]} for o in ordner if o["name"] in gruppen_namen]

    absender_email = daten.get("absender_email", "") or ""

    return templates.TemplateResponse("archivio_bearbeiten_modal.html", {
        "request": request, "kontakt": pseudo_kontakt, "ordner": ordner, "funktionen": funktionen,
        "telefon_typen": telefon_typen, "email_typen": email_typen,
        "action": f"/archivio-import/uebernehmen-bearbeitet?absender_email={quote_plus(absender_email)}",
        "modal": True, "zurueck_ordner_id": "",
    })


@router.post("/archivio-import/uebernehmen-bearbeitet")
async def archivio_uebernehmen_bearbeitet(request: Request, absender_email: str = ""):
    """Uebernimmt einen Kandidaten mit den vom Nutzer im Bearbeiten-Formular
    korrigierten Werten - im Gegensatz zu den anderen Uebernehmen-Routen wird der
    Kandidat NICHT erneut aus der Archivio-DB geholt (der Nutzer hat die Werte ja
    gerade bewusst geaendert), sondern direkt aus den abgeschickten Formulardaten
    aufgebaut (gleiche Hilfsfunktion _parse_kontakt_form wie beim Kontakt-Bearbeiten)."""
    form = await request.form()
    daten = _parse_kontakt_form(form)
    ordner_ids = {int(o) for o in form.getlist("ordner_ids")}

    conn = get_connection()
    try:
        ordner = queries.list_projekte(conn)
        daten["gruppen_als_ordner"] = [o["name"] for o in ordner if o["id"] in ordner_ids]
        queries.create_vorschlag(conn, daten, quelle="archivio")
        if absender_email:
            markiere_status(_signatur_db_pfad(), absender_email, "uebernommen")
    finally:
        conn.close()
    return RedirectResponse(url="/review", status_code=303)


@router.post("/archivio-import/ablehnen")
async def archivio_ablehnen(request: Request, email: str = Form(...)):
    """Lehnt genau EINEN Kandidaten ab - legt ihn als bereits 'abgelehnt' markierten
    Vorschlag an (damit er bei der naechsten Vorschau nicht wieder auftaucht) und
    markiert die zugrundeliegenden Mails in der Archivio-DB ebenfalls als 'abgelehnt'."""
    form = await request.form()
    postfaecher = form.getlist("postfaecher")
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        for daten in kandidaten:
            if daten["emails"] and daten["emails"][0]["email"].lower() == email.lower():
                _kandidat_ablehnen(conn, daten)
                break
    finally:
        conn.close()
    return RedirectResponse(url="/archivio-import", status_code=303)


@router.post("/archivio-import/ablehnen-ausgewaehlte")
async def archivio_ablehnen_ausgewaehlte(request: Request):
    """Lehnt mehrere ausgewaehlte Kandidaten auf einmal ab (Sammel-Leiste)."""
    form = await request.form()
    postfaecher = form.getlist("postfaecher")
    emails = {e.lower() for e in form.getlist("emails")}
    conn = get_connection()
    try:
        kandidaten, _ = _hole_kandidaten_oder_leer(conn, postfaecher)
        for daten in kandidaten:
            if daten["emails"] and daten["emails"][0]["email"].lower() in emails:
                _kandidat_ablehnen(conn, daten)
    finally:
        conn.close()
    return RedirectResponse(url="/archivio-import", status_code=303)
