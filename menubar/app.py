"""Rubrica – macOS Menubar-App. Startet, ueberwacht und beendet den Web-Server
und den CardDAV-Server (Radicale) als Kindprozesse. Ersetzt die vorherigen zwei
separaten launchd-Dienste durch einen einzigen Wrapper-Prozess mit sichtbarem
Menubar-Icon und einer Funktion zum sauberen Beenden - ohne Menubar-App gab es
kein Statusdisplay und "Beenden" haette wegen KeepAlive=true nur zum sofortigen
Neustart durch launchd gefuehrt (siehe docs/konzept.md Abschnitt 11)."""
from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import rumps

# Flacher Sibling-Import (kein "from menubar import updater"): im gepackten .app-
# Bundle liegt dieses Skript flach in Contents/Resources (als rubrica_menubar.py
# kopiert, siehe scripts/build-pkg.sh), updater.py wird als flache Geschwisterdatei
# mitkopiert - Pythons sys.path[0] ist beim direkten Skriptaufruf immer das
# Verzeichnis des laufenden Skripts, das funktioniert daher in Dev und Produktion
# identisch, ohne dass "menubar" ein echtes installiertes Package sein muesste.
import updater

# RADICALE_PORT bleibt bewusst fest (kein bekannter Konfliktfall, vermeidet
# Config-Drift zwischen diesem Wert und radicale.base_url in config.yaml).
RADICALE_PORT = 8443
# Muss mit sync.radicale.RADICALE_BENUTZER uebereinstimmen (hier dupliziert statt
# importiert, damit die Menubar-App ihre bewusst minimalen Abhaengigkeiten behaelt).
RADICALE_BENUTZER = "rubrica"

_HERE = Path(__file__).resolve().parent  # Contents/Resources im gepackten Bundle
_ICON = str(_HERE / "icon.png")
_DATA_DIR = Path.home() / "Library" / "Application Support" / "Rubrica"
_LOG_DIR = _DATA_DIR / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _web_port() -> int:
    """Liest server.port aus config.yaml (leichtgewichtig, ohne das volle config-
    Package zu importieren - bewusst minimale Abhaengigkeiten der Menubar-App).
    Faellt bei jedem Fehler (fehlende Datei, kaputtes YAML, fehlender Schluessel)
    auf 8001 zurueck - ein Port-Konflikt (z.B. mit einer anderen lokalen App im
    selben Buero) soll konfigurierbar sein, ohne die Menubar-App am Start zu hindern."""
    try:
        import yaml
        daten = yaml.safe_load((_DATA_DIR / "config.yaml").read_text(encoding="utf-8")) or {}
        return int(daten.get("server", {}).get("port", 8001))
    except Exception:
        return 8001


WEB_PORT = _web_port()

logging.basicConfig(
    filename=str(_LOG_DIR / "menubar.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def _local_version() -> str:
    try:
        return (_HERE / "VERSION").read_text().strip()
    except Exception:
        return "0.0.0"


_UPDATE_STATE_PFAD = _DATA_DIR / "update_state.json"
_UPDATE_PRUEF_INTERVALL = 24 * 60 * 60  # 24h


def _update_state_lesen() -> dict:
    try:
        return json.loads(_UPDATE_STATE_PFAD.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _update_state_schreiben(daten: dict) -> None:
    try:
        _UPDATE_STATE_PFAD.write_text(json.dumps(daten), encoding="utf-8")
    except Exception as exc:
        log.warning("Konnte update_state.json nicht schreiben: %s", exc)


def _hostname_local() -> str:
    try:
        out = subprocess.run(["scutil", "--get", "LocalHostName"],
                              capture_output=True, text=True, timeout=5)
        name = out.stdout.strip()
    except Exception:
        name = ""
    return f"{name or socket.gethostname()}.local"



def _env() -> dict:
    env = os.environ.copy()
    env["RUBRICA_DATA_DIR"] = str(_DATA_DIR)
    return env


def _osascript_alert(titel: str, nachricht: str):
    nachricht = nachricht.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(["osascript", "-e", f'display alert "{titel}" message "{nachricht}"'], timeout=30)
    except Exception as exc:
        log.warning("osascript-Dialog fehlgeschlagen: %s", exc)


def _bereite_datenverzeichnis_vor():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_DIR.mkdir(exist_ok=True)
    config = _DATA_DIR / "config.yaml"
    beispiel = _HERE / "config.yaml.example"
    if not config.exists() and beispiel.exists():
        config.write_text(beispiel.read_text())
        log.info("config.yaml aus Beispiel erstellt")


def _setze_config_radicale_passwort(passwort: str):
    """Traegt das generierte Radicale-Passwort in config.yaml ein (radicale.password),
    damit die Client-Seite (Push) mit der htpasswd-Server-Seite uebereinstimmt."""
    import yaml
    config = _DATA_DIR / "config.yaml"
    try:
        daten = yaml.safe_load(config.read_text()) or {}
        daten.setdefault("radicale", {})["password"] = passwort
        config.write_text(yaml.dump(daten, allow_unicode=True, default_flow_style=False, sort_keys=False))
        log.info("Radicale-Passwort in config.yaml gesetzt")
    except Exception as exc:
        log.warning("Konnte Radicale-Passwort nicht in config.yaml schreiben: %s", exc)


def _bereite_radicale_vor():
    """Zertifikat, Passwort und radicale.conf beim allerersten Start anlegen -
    portiert aus dem vorherigen Bash-Launcher 'Rubrica Radicale'."""
    (_DATA_DIR / "radicale").mkdir(parents=True, exist_ok=True)
    tls_dir = _DATA_DIR / "radicale-tls"
    hostname = _hostname_local()

    if not (tls_dir / "cert.pem").exists():
        subprocess.run(["/bin/bash", str(_HERE / "generate-cert.sh"), str(tls_dir), hostname],
                        check=False, timeout=30, env=_env())
        log.info("TLS-Zertifikat fuer %s erstellt", hostname)

    htpasswd = _DATA_DIR / "radicale-htpasswd"
    if not htpasswd.exists():
        passwort = secrets.token_urlsafe(12)
        subprocess.run([sys.executable, str(_HERE / "radicale_set_password.py"), RADICALE_BENUTZER, passwort],
                        check=False, timeout=30, env=_env())
        # Dasselbe generierte Passwort auch in config.yaml schreiben (Client-Seite),
        # damit Rubricas eigener Push von Anfang an gegen das gleiche Passwort
        # authentifiziert wie die htpasswd-Datei (Server-Seite) - sonst schluege der
        # Push bis zur ersten manuellen Passwortaenderung fehl.
        _setze_config_radicale_passwort(passwort)
        zugangsdaten = _DATA_DIR / "RADICALE-ZUGANGSDATEN.txt"
        zugangsdaten.write_text(
            f"Rubrica CardDAV-Zugangsdaten (generiert {time.strftime('%c')})\n"
            f"Server:   {hostname}\n"
            f"Port:     {RADICALE_PORT}\n"
            f"Benutzer: {RADICALE_BENUTZER}\n"
            f"Passwort: {passwort}\n"
            f"Pfad:     /{RADICALE_BENUTZER}/kontakte/\n"
        )
        zugangsdaten.chmod(0o600)
        _osascript_alert(
            "Rubrica CardDAV eingerichtet",
            f"Server: {hostname}\nPort: {RADICALE_PORT}\n"
            f"Benutzer: {RADICALE_BENUTZER}\nPasswort: {passwort}\n"
            f"Pfad: /{RADICALE_BENUTZER}/kontakte/\n\n"
            f"Auch gespeichert in:\n{zugangsdaten}",
        )
        log.info("Radicale-Passwort erzeugt, Zugangsdaten gespeichert")

    conf = _DATA_DIR / "radicale.conf"
    if not conf.exists():
        beispiel = _HERE / "config" / "radicale.conf.example"
        text = beispiel.read_text().replace("__RUBRICA_DATA_DIR__", str(_DATA_DIR))
        conf.write_text(text)


class Kindprozess:
    """Startet, ueberwacht und beendet einen Kindprozess (Uvicorn oder Radicale).
    Ersetzt die Ueberwachung, die frueher launchd (KeepAlive) pro Dienst separat
    uebernommen hat - jetzt gibt es nur noch einen launchd-Job (diese Menubar-App),
    daher muss sie ihre Kindprozesse selbst neu starten, falls einer abstuerzt."""

    def __init__(self, name: str, befehl: list, log_datei: Path):
        self.name = name
        self.befehl = befehl
        self.log_datei = log_datei
        self.proc: subprocess.Popen | None = None

    def start(self):
        self.log_datei.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.log_datei, "a")
        self.proc = subprocess.Popen(self.befehl, cwd=str(_HERE), env=_env(), stdout=f, stderr=f)
        log.info("%s gestartet (PID %s)", self.name, self.proc.pid)

    def lebt(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def stop(self):
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=8)
        except Exception:
            self.proc.kill()
        log.info("%s gestoppt", self.name)
        self.proc = None


def _server_antwortet() -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{WEB_PORT}/kontakte", timeout=2).status_code == 200
    except Exception:
        return False


def _radicale_antwortet() -> bool:
    """Ein reiner TCP-Connect (ohne TLS-Handshake) liess Radicale bei jedem Check
    einen "SSL: UNEXPECTED_EOF_WHILE_READING"-Fehler loggen (Verbindung wird vor
    dem ClientHello wieder geschlossen) - das fluteten Radicales eigenes Fehlerlog
    alle 15s mit fuers Debugging irrelevantem Rauschen. Ein echter HTTPS-Request
    (Antwort-Status ist egal, 401 zaehlt auch als "laeuft") vermeidet das."""
    try:
        httpx.get(f"https://127.0.0.1:{RADICALE_PORT}/", timeout=2, verify=False)
        return True
    except Exception:
        return False


class RubricaApp(rumps.App):
    def __init__(self):
        super().__init__("Rubrica", icon=_ICON, template=True, quit_button=None)

        self._version_item = rumps.MenuItem(f"Version {_local_version()}")
        self._server_item = rumps.MenuItem("⬤  Web-Server …")
        self._radicale_item = rumps.MenuItem("⬤  CardDAV (Radicale) …")
        self._update_item = None  # erst eingefuegt, sobald ein Update gefunden wurde

        self.menu = [
            self._version_item,
            rumps.separator,
            self._server_item,
            self._radicale_item,
            rumps.separator,
            rumps.MenuItem("Rubrica öffnen", callback=self.oeffnen),
            rumps.MenuItem("Datenordner öffnen", callback=self.datenordner_oeffnen),
            rumps.MenuItem("Nach Updates suchen…", callback=self.update_jetzt_pruefen),
            rumps.separator,
            rumps.MenuItem("Beenden", callback=self.beenden),
        ]

        _bereite_datenverzeichnis_vor()
        _bereite_radicale_vor()

        self.server = Kindprozess(
            "Web-Server",
            [sys.executable, "-m", "uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", str(WEB_PORT)],
            _LOG_DIR / "server.log",
        )
        self.radicale = Kindprozess(
            "Radicale",
            [sys.executable, "-m", "radicale", "--config", str(_DATA_DIR / "radicale.conf")],
            _LOG_DIR / "radicale.log",
        )
        self.server.start()
        self.radicale.start()
        self._status_aktualisieren()

        threading.Thread(target=self._ueberwachung, daemon=True).start()
        threading.Thread(target=self._update_ueberwachung, daemon=True).start()

    def _ueberwachung(self):
        while True:
            time.sleep(15)
            if not self.server.lebt():
                log.warning("Web-Server nicht aktiv - Neustart")
                self.server.start()
            if not self.radicale.lebt():
                log.warning("Radicale nicht aktiv - Neustart")
                self.radicale.start()
            self._status_aktualisieren()

    def _update_ueberwachung(self):
        """Erste Pruefung 60s nach dem Start, danach alle 24h - matcht das gleiche
        Hintergrund-Thread-Muster wie _ueberwachung()."""
        time.sleep(60)
        while True:
            self._update_pruefen(manuell=False)
            time.sleep(_UPDATE_PRUEF_INTERVALL)

    def _update_pruefen(self, manuell: bool):
        info = updater.pruefe_update(_local_version(), log=log)
        if info is None:
            if manuell:
                rumps.notification("Rubrica", "", "Sie verwenden bereits die neueste Version.")
            return

        if self._update_item is None:
            self._update_item = rumps.MenuItem(
                f"Update auf v{info.version} verfügbar", callback=self.update_anwenden
            )
            self.menu.insert_before(self._version_item.title, self._update_item)
        else:
            self._update_item.title = f"Update auf v{info.version} verfügbar"
        self._update_info = info

        state = _update_state_lesen()
        bereits_gemeldet = state.get("gemeldete_version") == info.version
        if manuell or not bereits_gemeldet:
            rumps.notification(
                "Rubrica-Update verfügbar", f"Version {info.version}",
                "Im Menü auf \"Update auf v%s verfügbar\" klicken, um es zu installieren." % info.version,
            )
            _update_state_schreiben({"gemeldete_version": info.version})

    def update_jetzt_pruefen(self, _):
        threading.Thread(target=self._update_pruefen, args=(True,), daemon=True).start()

    def update_anwenden(self, _):
        threading.Thread(target=self._update_herunterladen_und_installieren, daemon=True).start()

    def _update_herunterladen_und_installieren(self):
        info = getattr(self, "_update_info", None)
        if info is None:
            return
        rumps.notification("Rubrica", "", f"Lade Update {info.version} herunter…")
        pkg = updater.lade_und_pruefe(info, log=log)
        if pkg is None:
            rumps.notification("Rubrica", "", "Update konnte nicht verifiziert werden - Installation abgebrochen.")
            return
        updater.installiere(pkg)

    def _status_aktualisieren(self):
        server_ok = _server_antwortet()
        radicale_ok = _radicale_antwortet()
        self._server_item.title = f"{'🟢' if server_ok else '🔴'}  Web-Server {'läuft' if server_ok else 'startet…'}"
        self._radicale_item.title = f"{'🟢' if radicale_ok else '🔴'}  CardDAV {'läuft' if radicale_ok else 'startet…'}"

    def oeffnen(self, _):
        subprocess.run(["open", f"http://127.0.0.1:{WEB_PORT}"])

    def datenordner_oeffnen(self, _):
        subprocess.run(["open", str(_DATA_DIR)])

    def beenden(self, _):
        log.info("Beenden ausgeloest")
        self.server.stop()
        self.radicale.stop()
        # Launchd-Job entladen, sonst startet KeepAlive=true die App sofort neu.
        try:
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/ch.rubrica.server"], timeout=5)
        except Exception as exc:
            log.warning("launchctl bootout fehlgeschlagen: %s", exc)
        rumps.quit_application()


if __name__ == "__main__":
    try:
        RubricaApp().run()
    except Exception:
        log.exception("Fataler Fehler in der Menubar-App")
        raise
