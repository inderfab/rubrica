"""Gemeinsame Ressourcen fuer alle web-Module (Templates, Filter)."""
from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path
from urllib.parse import quote_plus
from fastapi.templating import Jinja2Templates
from packaging.version import Version

from config import settings
from db.connection import get_connection

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


def _hostname_local() -> str:
    """Der Rechnername, den man in Kontakte.app als CardDAV-Server eintraegt -
    gemeinsam genutzt vom Setup-Assistenten (web/setup.py) und den Einstellungen
    (web/settings.py, zeigt denselben Wert nochmal an, siehe dortiger Kommentar)."""
    try:
        out = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5)
        name = out.stdout.strip()
    except Exception:
        name = ""
    return f"{name or socket.gethostname()}.local"


def importiere_kontakte_app_und_synchronisiere(conn) -> dict:
    """Importiert aus Kontakte.app und pusht die betroffenen Kontakte anschliessend
    nach Radicale - gemeinsam genutzt von web/setup.py (Einrichtungsassistent) und
    web/imports.py (regulaerer Import), damit beide Aufrufer nicht getrennt daran
    denken muessen (importer/contacts_app.py selbst pusht bewusst nicht, siehe
    dessen Docstring - Push ist Aufgabe der Web-Schicht, analog zu importer/vcard.py)."""
    from importer.contacts_app import importiere_aus_kontakte_app
    from sync import radicale
    ergebnis = importiere_aus_kontakte_app(conn)
    kontakt_ids = ergebnis.pop("kontakt_ids", [])
    for kontakt_id in kontakt_ids:
        radicale.push_kontakt_mit_ordnern(conn, kontakt_id)
    return ergebnis


def _setup_erforderlich() -> bool:
    """Zeigt den Setup-Assistenten nur bei einer wirklich frischen Installation.
    Bestehende Installationen mit bereits vorhandenen Kontakten setzen den Marker
    hier automatisch (kein Assistent fuer bestehende Nutzer, siehe Kapitel 5 der
    Distributionsfaehigkeit-Arbeit, docs/CHANGELOG-INTERN.md)."""
    if settings.get("setup.completed", False):
        return False
    conn = get_connection()
    try:
        anzahl = conn.execute("SELECT COUNT(*) FROM kontakte").fetchone()[0]
    finally:
        conn.close()
    if anzahl > 0:
        settings.save({"setup": {"completed": True}})
        return False
    return True


# Aufrufbares Jinja-Global (gleiches Prinzip wie archivio_konfiguriert): der
# Zustand kann sich waehrend der Anfrage-Bearbeitung aendern (Setup abgeschlossen),
# ein einmalig berechneter Wert waere sofort veraltet.
templates.env.globals["setup_erforderlich"] = _setup_erforderlich


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


def _update_verfuegbar() -> str:
    """Liest die zuletzt vom Update-Checker (menubar/updater.py, separater Prozess)
    gefundene Version aus update_state.json - gemeinsames Dateisystem ist die
    Schnittstelle zwischen Menubar- und Web-Prozess. Gibt die neue Versionsnummer
    zurueck (fuer den Sidebar-Hinweis), oder "" falls kein Update bekannt ist oder
    die laufende Version bereits aktuell/neuer ist (z.B. nach einem erfolgten
    Update - kein explizites Aufraeumen der Datei noetig)."""
    pfad = settings.daten_verzeichnis() / "update_state.json"
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        verfuegbare_version = daten.get("gemeldete_version", "")
        if verfuegbare_version and Version(verfuegbare_version) > Version(APP_VERSION):
            return verfuegbare_version
    except Exception:
        pass
    return ""


templates.env.globals["update_verfuegbar"] = _update_verfuegbar

# Fuer JSON-Daten in HTML-Attributen (z.B. Combobox-Optionen): Jinjas normales
# Autoescaping wandelt die enthaltenen Anfuehrungszeichen in &quot; um, der
# Browser dekodiert das beim Attribut-Parsing wieder zurueck - das JSON bleibt
# beim Lesen ueber element.dataset also intakt.
templates.env.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)

# Fuer per Hand zusammengesetzte hx-get/href-Query-Strings (z.B. E-Mail-Adressen
# als Parameter) - Jinja2 bringt anders als Flask kein urlencode-Filter mit.
templates.env.filters["urlencode"] = lambda value: quote_plus(str(value))
