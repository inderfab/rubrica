"""Gemeinsame Ressourcen fuer alle web-Module (Templates, Filter)."""
from __future__ import annotations

import json
from pathlib import Path
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)

# Fuer JSON-Daten in HTML-Attributen (z.B. Combobox-Optionen): Jinjas normales
# Autoescaping wandelt die enthaltenen Anfuehrungszeichen in &quot; um, der
# Browser dekodiert das beim Attribut-Parsing wieder zurueck - das JSON bleibt
# beim Lesen ueber element.dataset also intakt.
templates.env.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)
