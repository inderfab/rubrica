from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from db import queries
from db.connection import get_connection
from sync import radicale
from web.shared import templates

router = APIRouter()


@router.get("/ordner")
def ordner_liste(request: Request):
    conn = get_connection()
    try:
        ordner = queries.list_projekte(conn)
        for o in ordner:
            o["anzahl_kontakte"] = conn.execute(
                "SELECT COUNT(*) FROM kontakte_projekte WHERE projekt_id = ?", (o["id"],)
            ).fetchone()[0]
    finally:
        conn.close()
    return templates.TemplateResponse("folders.html", {"request": request, "ordner": ordner})


@router.post("/ordner/neu")
def ordner_neu(name: str = Form(...)):
    name = name.strip()
    if name:
        conn = get_connection()
        try:
            ordner_id = queries.get_or_create_projekt(conn, name)
            radicale.push_projekt(conn, ordner_id)
        finally:
            conn.close()
    return RedirectResponse(url="/ordner", status_code=303)


@router.post("/ordner/{ordner_id}/loeschen")
def ordner_loeschen(ordner_id: int):
    conn = get_connection()
    try:
        queries.delete_projekt(conn, ordner_id)
        radicale.delete_projekt(ordner_id)
    finally:
        conn.close()
    return RedirectResponse(url="/ordner", status_code=303)
