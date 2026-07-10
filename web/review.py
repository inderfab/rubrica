from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from db import queries
from db.connection import get_connection
from sync import radicale
from web.shared import templates

router = APIRouter()


@router.get("/review")
def review_liste(request: Request):
    conn = get_connection()
    try:
        vorschlaege = queries.list_vorschlaege(conn, status="offen")
    finally:
        conn.close()
    return templates.TemplateResponse("review_queue.html", {"request": request, "vorschlaege": vorschlaege})


@router.post("/review/{vorschlag_id}/bestaetigen")
def review_bestaetigen(vorschlag_id: int):
    conn = get_connection()
    try:
        kontakt_id = queries.bestaetige_vorschlag(conn, vorschlag_id)
        radicale.push_kontakt(conn, kontakt_id)
        for p in queries.get_kontakt(conn, kontakt_id)["projekte"]:
            radicale.push_projekt(conn, p["id"])
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
