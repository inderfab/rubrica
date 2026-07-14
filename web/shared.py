"""Gemeinsame Ressourcen fuer alle web-Module (Templates, Filter)."""
from __future__ import annotations

import json
from pathlib import Path
from fastapi.templating import Jinja2Templates

from config import settings

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)

def _archivio_konfiguriert() -> bool:
    """Prueft nicht nur, ob ein Pfad eingetragen ist, sondern ob dort tatsaechlich eine
    Datei liegt - ein veralteter/falscher Pfad soll den Nav-Punkt nicht anzeigen."""
    db_pfad = (settings.get("archivio.signatur_db_path", "") or "").strip()
    return bool(db_pfad) and Path(db_pfad).is_file()


# Als aufrufbares Jinja-Global (nicht als einmalig berechneter Wert wie app_version),
# damit die Navigation den aktuellen Stand sofort zeigt, wenn archivio.signatur_db_path in
# den Einstellungen geaendert wird - settings.get() liest bei jedem Aufruf den
# aktuellen (bei save() neu geladenen) Konfigurationsstand.
templates.env.globals["archivio_konfiguriert"] = _archivio_konfiguriert

# Fuer Cache-Busting bei statischen Dateien (style.css, app.js): ohne Versions-
# Query-Parameter behaelt der Browser nach einem App-Update oft die alte,
# gecachte Version dieser Dateien bei (URL bleibt unveraendert) - das fuehrte
# schon dazu, dass ein neues Feature im Browser unsichtbar blieb, obwohl der
# Server bereits die neue Version auslieferte.
try:
    _VERSION_PATH = Path(__file__).resolve().parent.parent / "VERSION"
    APP_VERSION = _VERSION_PATH.read_text(encoding="utf-8").strip()
except Exception:
    APP_VERSION = "0.0.0"
templates.env.globals["app_version"] = APP_VERSION

# Fuer JSON-Daten in HTML-Attributen (z.B. Combobox-Optionen): Jinjas normales
# Autoescaping wandelt die enthaltenen Anfuehrungszeichen in &quot; um, der
# Browser dekodiert das beim Attribut-Parsing wieder zurueck - das JSON bleibt
# beim Lesen ueber element.dataset also intakt.
templates.env.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)
