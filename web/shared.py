"""Gemeinsame Ressourcen fuer alle web-Module (Templates, Filter)."""
from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path
from urllib.parse import quote_plus
from fastapi import Request
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


def _eigene_ip_adressen() -> set:
    """Alle IP-Adressen, unter denen dieser Rechner selbst erreichbar ist. Der
    Bonjour-Hostname (z.B. "windows.local", siehe _hostname_local) loest auf die
    tatsaechliche LAN-Interface-Adresse auf, NICHT auf 127.0.0.1 - ruft man ihn also
    direkt am Server-Rechner selbst im Browser auf, sieht request.client.host die
    LAN-IP, nicht "localhost"/"127.0.0.1". Ein reiner Loopback-Vergleich block­ierte
    dadurch faelschlich sogar den Zugriff auf dem Server-Rechner selbst."""
    adressen = {"127.0.0.1", "::1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            adressen.add(info[4][0])
    except Exception:
        pass
    try:
        # Ermittelt die tatsaechlich nach aussen genutzte Interface-IP zuverlaessiger
        # als gethostname()/getaddrinfo (die bei mDNS/.local-Namen manchmal leer bzw.
        # unvollstaendig sind) - "connect" auf UDP baut keine echte Verbindung auf,
        # der Kernel waehlt aber schon dabei das ausgehende Interface.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            adressen.add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    return adressen


def _ist_lokale_maschine(request: Request) -> bool:
    """Prueft, ob eine Anfrage tatsaechlich vom Server-Rechner selbst kommt (nicht
    nur ueber "localhost"/"127.0.0.1", sondern auch ueber dessen eigene LAN-IP bzw.
    Bonjour-Hostnamen aufgerufen, siehe _eigene_ip_adressen) - gemeinsam genutzt vom
    Setup-Assistenten (web/setup.py) und dem Kontakte.app-Import (web/imports.py),
    die beide sicherheitskritisch nur lokal erreichbar sein duerfen."""
    host = request.client.host if request.client else ""
    return host in _eigene_ip_adressen()


def importiere_kontakte_app_und_synchronisiere(conn, fortschritt_callback=None) -> dict:
    """Importiert aus Kontakte.app und pusht die betroffenen Kontakte anschliessend
    nach Radicale - gemeinsam genutzt von web/setup.py (Einrichtungsassistent) und
    web/imports.py (regulaerer Import), damit beide Aufrufer nicht getrennt daran
    denken muessen (importer/contacts_app.py selbst pusht bewusst nicht, siehe
    dessen Docstring - Push ist Aufgabe der Web-Schicht, analog zu importer/vcard.py).

    fortschritt_callback(phase, verarbeitet, gesamt) wird waehrend beider Phasen
    aufgerufen ("importiere" bzw. "synchronisiere"), phase="lese" einmalig davor
    (die AppleScript-Abfrage selbst laesst sich nicht granular verfolgen)."""
    from importer.contacts_app import importiere_aus_kontakte_app
    from sync import radicale

    def _import_fortschritt(verarbeitet, gesamt):
        if fortschritt_callback is not None:
            fortschritt_callback("importiere", verarbeitet, gesamt)

    if fortschritt_callback is not None:
        fortschritt_callback("lese", 0, 0)
    ergebnis = importiere_aus_kontakte_app(conn, fortschritt_callback=_import_fortschritt)
    kontakt_ids = ergebnis.pop("kontakt_ids", [])

    # Eine Verbindung fuer den ganzen Push-Batch wiederverwenden statt pro Kontakt
    # eine eigene TLS-Verbindung aufzubauen - bei 1000+ Kontakten war genau das
    # bisher der groesste Teil der Laufzeit (siehe sync.radicale.sync_alle, wo
    # dieselbe Optimierung schon fuer den Voll-Sync dokumentiert ist).
    client = radicale._client()
    try:
        for i, kontakt_id in enumerate(kontakt_ids):
            radicale.push_kontakt_mit_ordnern(conn, kontakt_id, client=client)
            if fortschritt_callback is not None:
                fortschritt_callback("synchronisiere", i + 1, len(kontakt_ids))
    finally:
        if client is not None:
            client.close()
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


def _mail_konfiguriert() -> bool:
    return bool((settings.get("mail.host", "") or "").strip())


templates.env.globals["mail_konfiguriert"] = _mail_konfiguriert


def _vorschlaege_konfiguriert() -> bool:
    """Steuert den Nav-Punkt "Vorschläge": sichtbar sobald mindestens eine der
    beiden Quellen aktiv ist (Mail-Eingang ODER Radicale-Sync, ueber den
    Kontakte.app-Neuzugaenge erkannt werden - siehe kontakte_app_intake.py).
    Bewusst nicht mehr nur an mail_konfiguriert() gekoppelt: Radicale-Sync ist in
    der Praxis quasi immer aktiv (kein An/Aus-Schalter), waehrend Mail-Eingang
    optional bleibt - ohne diese Erweiterung waere die Seite ohne konfiguriertes
    Mail-Postfach ueber die Navigation gar nicht erreichbar gewesen."""
    import kontakte_app_intake
    return _mail_konfiguriert() or kontakte_app_intake.konfiguriert()


templates.env.globals["vorschlaege_konfiguriert"] = _vorschlaege_konfiguriert


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


def _typ_optionen(optionen: list, aktueller_wert: str) -> list:
    """Optionsliste eines Kategorie-Dropdowns inklusive des tatsaechlich am Datensatz
    stehenden Werts. Ohne diese Ergaenzung waere ein nicht (mehr) konfigurierter
    Bestandswert im <select> nicht enthalten - der Browser zeigt dann kommentarlos
    die erste Option an und das blosse Oeffnen und Speichern eines Kontakts wuerde
    dessen Kategorie still veraendern. Aufraeumen soll ausdruecklich nur ueber
    /einstellungen/kategorien passieren, nicht als Nebenwirkung."""
    liste = list(optionen)
    wert = (aktueller_wert or "").strip()
    if wert and wert not in liste:
        liste.append(wert)
    return liste


templates.env.globals["typ_optionen"] = _typ_optionen
