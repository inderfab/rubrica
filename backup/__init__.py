"""Automatisches Backup der SQLite-Datenbank an einen konfigurierbaren Pfad
(z. B. ein NAS-Share) - nach jeder aendernden Anfrage ausgeloest (siehe die
Middleware in web/main.py). Nutzt sqlite3s eingebaute Backup-API statt einer
rohen Dateikopie, damit auch waehrend eines laufenden Schreibzugriffs immer ein
konsistenter Snapshot entsteht."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from config import settings
from db.connection import get_connection

_LOG = logging.getLogger(__name__)

DATEINAME = "rubrica-backup.sqlite"


def sichern_falls_konfiguriert() -> None:
    """Schreibt (bzw. ueberschreibt) eine einzelne Backup-Datei am konfigurierten
    Pfad. Best-effort: schlaegt der Zielpfad fehl (z. B. NAS nicht erreichbar),
    wird nur geloggt - eine normale Kontakt-Aenderung darf dadurch nie fehlschlagen."""
    ordner = (settings.get("backup.pfad", "") or "").strip()
    if not ordner:
        return
    try:
        ziel_ordner = Path(ordner)
        ziel_ordner.mkdir(parents=True, exist_ok=True)
        ziel_pfad = ziel_ordner / DATEINAME

        quelle = get_connection()
        try:
            ziel = sqlite3.connect(str(ziel_pfad))
            try:
                quelle.backup(ziel)
            finally:
                ziel.close()
        finally:
            quelle.close()
    except Exception:
        _LOG.exception("Backup nach '%s' fehlgeschlagen", ordner)
