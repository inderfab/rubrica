"""Phase 3: Export einer Kontaktliste (Ordner) als PDF/CSV/vCard, gebuendelt in einem ZIP."""
from __future__ import annotations

import re
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from config import settings
from db import queries
from db.connection import get_connection
from export import generator
from web.shared import templates

router = APIRouter()


def _dateiname_sicher(text: str) -> str:
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE).strip().replace(" ", "_")
    return text or "Export"


LOGO_ERLAUBTE_ENDUNGEN = {".png", ".jpg", ".jpeg", ".gif"}


def _logo_entfernen() -> None:
    for alte_datei in settings.daten_verzeichnis().glob(f"{settings.LOGO_STAMM}.*"):
        alte_datei.unlink(missing_ok=True)


@router.get("/export")
def export_form(request: Request, fehler: str = "", gespeichert: str = ""):
    conn = get_connection()
    try:
        ordner = queries.list_projekte(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("export.html", {
        "request": request, "ordner": ordner, "fehler": fehler,
        "gespeichert": bool(gespeichert),
        # Darstellungs-Einstellungen stehen hier statt unter /einstellungen
        # (Nutzer-Vorgabe): sie wirken sich ausschliesslich auf diesen Export aus.
        "export_firmenname": settings.get("export.firmenname", "") or "",
        "logo_vorhanden": settings.logo_pfad() is not None,
        "privates_telefon_zeigen": bool(settings.get("export.privates_telefon_zeigen", False)),
        "private_email_zeigen": bool(settings.get("export.private_email_zeigen", False)),
        "privatadresse_zeigen": bool(settings.get("export.privatadresse_zeigen", False)),
    })


@router.get("/export/logo")
def export_logo():
    pfad = settings.logo_pfad()
    if pfad is None:
        return Response(status_code=404)
    return FileResponse(pfad)


@router.post("/export/logo/entfernen")
def export_logo_entfernen():
    _logo_entfernen()
    return RedirectResponse(url="/export?gespeichert=1", status_code=303)


@router.post("/export/einstellungen")
async def export_einstellungen_speichern(request: Request):
    """Bewusst eine eigene Route und nicht die allgemeine Einstellungen-Route: die
    speichert saemtliche Abschnitte auf einmal und wuerde die hier nicht
    vorhandenen Felder (Mail, Archivio, Backup) mit Leerwerten ueberschreiben."""
    form = await request.form()

    logo = form.get("logo")
    if logo is not None and getattr(logo, "filename", ""):
        endung = Path(logo.filename).suffix.lower()
        if endung in LOGO_ERLAUBTE_ENDUNGEN:
            _logo_entfernen()
            ziel = settings.daten_verzeichnis() / f"{settings.LOGO_STAMM}{endung}"
            ziel.write_bytes(await logo.read())

    settings.save({"export": {
        "firmenname": (form.get("export_firmenname") or "").strip(),
        "privates_telefon_zeigen": form.get("privates_telefon_zeigen") is not None,
        "private_email_zeigen": form.get("private_email_zeigen") is not None,
        "privatadresse_zeigen": form.get("privatadresse_zeigen") is not None,
    }})
    return RedirectResponse(url="/export?gespeichert=1", status_code=303)


@router.post("/export")
async def export_erzeugen(request: Request):
    form = await request.form()
    ordner_id = (form.get("ordner_id") or "").strip()
    formate = form.getlist("formate")

    if not formate:
        return RedirectResponse(url="/export?fehler=formate", status_code=303)

    conn = get_connection()
    try:
        ordner_id_int = int(ordner_id) if ordner_id else None
        if ordner_id_int:
            row = conn.execute("SELECT name FROM projekte WHERE id = ?", (ordner_id_int,)).fetchone()
            ordner_name = row["name"] if row else "Ordner"
        else:
            ordner_name = "Alle Kontakte"
        kontakte = queries.list_kontakte(conn, projekt_id=ordner_id_int)
    finally:
        conn.close()

    basisname = _dateiname_sicher(ordner_name)
    datum = datetime.now().strftime("%Y-%m-%d")

    firmenname = settings.get("export.firmenname", "") or ""
    logo = settings.logo_pfad()

    puffer = BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if "pdf" in formate:
            zf.writestr(
                f"{basisname}_{datum}.pdf",
                generator.kontakte_pdf(
                    ordner_name, kontakte, firmenname=firmenname,
                    logo_pfad=str(logo) if logo else "",
                    privates_telefon_zeigen=bool(settings.get("export.privates_telefon_zeigen", False)),
                    private_email_zeigen=bool(settings.get("export.private_email_zeigen", False)),
                    privatadresse_zeigen=bool(settings.get("export.privatadresse_zeigen", False)),
                ),
            )
        if "csv" in formate:
            zf.writestr(f"{basisname}_{datum}.csv", generator.kontakte_csv(kontakte))
        if "vcard" in formate:
            zf.writestr(f"{basisname}_{datum}.vcf", generator.kontakte_vcard(kontakte))

    dateiname = f"{basisname}_{datum}.zip"
    return Response(
        content=puffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )
