"""Automatische Updates fuer Rubrica Server. Prueft GitHub Releases, laedt das
signierte .pkg herunter, verifiziert Signatur + Team-ID und oeffnet den
System-Installer. Keine eigene Kryptografie - Sicherheitsanker ist
ausschliesslich Apples Developer-ID-Signaturkette (siehe Kapitel 1 der
Distributionsfaehigkeit-Arbeit, docs/CHANGELOG-INTERN.md, fuer die echte
Signierung/Notarisierung, ohne die dieser Check nie einen Treffer liefert)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
from packaging.version import InvalidVersion, Version

GITHUB_REPO = "inderfab/rubrica"
ASSET_SUFFIX = ".pkg"
ASSET_NAME_HINT = "rubrica-server"
# Gleiche Team-ID wie die Schwester-App Archivio (dasselbe Apple-Developer-Konto
# signiert beide, siehe docs/CHANGELOG-INTERN.md Kapitel 1).
EXPECTED_TEAM_ID = "2USYCLVGTM"

_DOWNLOAD_DIR = Path.home() / "Library" / "Caches" / "Rubrica" / "updates"


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    asset_name: str


def _log_info(log, msg, *args):
    if log:
        log.info(msg, *args)


def _log_warning(log, msg, *args):
    if log:
        log.warning(msg, *args)


def pruefe_update(current_version: str, log=None) -> "UpdateInfo | None":
    """Prueft GitHub Releases auf eine neuere Version mit passendem .pkg-Asset.
    Gibt bei jedem Fehler (Netzwerk, Parsing, ungueltige Version, kein passendes
    Asset, nicht neuer) None zurueck - die Pruefung darf den Nutzer nie stoeren."""
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=10,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code != 200:
            return None
        daten = resp.json()
        remote_version = daten.get("tag_name", "").lstrip("v")
        if not remote_version:
            return None
        if not (Version(remote_version) > Version(current_version)):
            return None
        for asset in daten.get("assets", []):
            name = asset.get("name", "")
            if ASSET_NAME_HINT in name and name.endswith(ASSET_SUFFIX):
                return UpdateInfo(
                    version=remote_version,
                    download_url=asset["browser_download_url"],
                    asset_name=name,
                )
        return None
    except InvalidVersion as exc:
        _log_warning(log, "Ungueltige Versionsangabe beim Update-Check: %s", exc)
        return None
    except Exception as exc:
        _log_warning(log, "Update-Check fehlgeschlagen: %s", exc)
        return None


def _verify_pkg(pkg: Path, log=None) -> bool:
    """Verifiziert ein heruntergeladenes .pkg per pkgutil (Signatur + Team-ID)
    und spctl (Gatekeeper-Installations-Check)."""
    try:
        r = subprocess.run(
            ["pkgutil", "--check-signature", str(pkg)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            _log_warning(log, "pkgutil --check-signature fehlgeschlagen: %s", r.stdout)
            return False
        if "Developer ID Installer" not in r.stdout:
            _log_warning(log, "Kein Developer-ID-Installer-Signer: %s", r.stdout)
            return False
        if f"({EXPECTED_TEAM_ID})" not in r.stdout:
            _log_warning(log, "Unerwartete Team-ID: %s", r.stdout)
            return False
    except Exception as exc:
        _log_warning(log, "pkgutil-Aufruf fehlgeschlagen: %s", exc)
        return False

    try:
        r = subprocess.run(
            ["spctl", "-a", "-t", "install", str(pkg)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            _log_warning(log, "spctl lehnt Paket ab: %s", r.stderr)
            return False
    except Exception as exc:
        _log_warning(log, "spctl-Aufruf fehlgeschlagen: %s", exc)
        return False

    return True


def lade_und_pruefe(info: UpdateInfo, log=None) -> "Path | None":
    """Laedt das Update-Paket herunter und verifiziert Signatur + Team-ID.
    Gibt den Pfad zum verifizierten .pkg zurueck, oder None (Datei wird bei
    jeder fehlgeschlagenen Pruefung geloescht)."""
    _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ziel = _DOWNLOAD_DIR / info.asset_name
    try:
        with httpx.stream("GET", info.download_url, timeout=60, follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(ziel, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
    except Exception as exc:
        _log_warning(log, "Update-Download fehlgeschlagen: %s", exc)
        ziel.unlink(missing_ok=True)
        return None

    if not _verify_pkg(ziel, log):
        ziel.unlink(missing_ok=True)
        return None

    _log_info(log, "Update %s heruntergeladen und verifiziert: %s", info.version, ziel)
    return ziel


def installiere(pkg: Path) -> None:
    """Oeffnet den System-Installer fuer das .pkg - kein stiller Root-Install.
    Bewusst ueber `open` statt osascript-Fernsteuerung: Kapitel 1s Postinstall
    braucht `launchctl bootstrap` innerhalb derselben GUI-Sitzung, was ueber den
    osascript-"with administrator privileges"-Weg bereits einmal fehlgeschlagen ist."""
    subprocess.run(["open", str(pkg)])
