"""Bedienungsanleitung als eigener Reiter in der App (/anleitung).

Der Inhalt liegt in web/templates/_anleitung_inhalt.html und wird 1:1 auch von
der oeffentlichen Website (docs/docs.html) verwendet - dort erzeugt
scripts/build-website.py die statische Seite aus derselben Datei. Dadurch kann
die Anleitung nie zwischen Website und installierter App auseinanderlaufen.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from web.shared import templates

router = APIRouter()


@router.get("/anleitung")
def anleitung_seite(request: Request):
    return templates.TemplateResponse("anleitung.html", {"request": request})
