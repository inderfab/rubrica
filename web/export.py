"""Phase 3: Export einer Kontaktliste (Ordner) als PDF/CSV/vCard, gebuendelt in einem ZIP."""
from __future__ import annotations

import re
import zipfile
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from config import settings
from db import queries
from db.connection import get_connection
from export import generator
from web.shared import templates

router = APIRouter()


def _dateiname_sicher(text: str) -> str:
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE).strip().replace(" ", "_")
    return text or "Export"


@router.get("/export")
def export_form(request: Request, fehler: str = ""):
    conn = get_connection()
    try:
        ordner = queries.list_projekte(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("export.html", {
        "request": request, "ordner": ordner, "fehler": fehler,
    })


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
