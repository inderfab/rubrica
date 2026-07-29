"""Einstellungsseite - fuer Konfigurationswerte, die bisher nur per Hand in
config.yaml editierbar waren (z.B. Archivio-Anbindung). Vermeidet, dass Nutzer
YAML von Hand bearbeiten muessen (Fehlerquelle: Tippfehler, falsche Einrueckung,
fehlende Sektion bei Installationen mit aelterem config.yaml)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

import mail_intake
from config import settings
from db.connection import get_connection
from sync import htpasswd, radicale
from web.shared import _hostname_local, templates

router = APIRouter()

LOGO_ERLAUBTE_ENDUNGEN = {".png", ".jpg", ".jpeg", ".gif"}


def _logo_entfernen() -> None:
    for alte_datei in settings.daten_verzeichnis().glob(f"{settings.LOGO_STAMM}.*"):
        alte_datei.unlink(missing_ok=True)


def _ca_zertifikat_pfad() -> Path:
    return settings.daten_verzeichnis() / "radicale-tls" / "ca-cert.pem"


@router.get("/einstellungen")
def einstellungen_form(request: Request, gespeichert: str = "", sync: str = "", mail: str = ""):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "gespeichert": bool(gespeichert),
        "sync_ergebnis": sync,
        "mail_ergebnis": mail,
        "archivio_signatur_db_path": settings.get("archivio.signatur_db_path", "") or "",
        "archivio_min_mails": settings.get("archivio.min_mails", 2),
        "archivio_eigene_domains": ", ".join(settings.get("archivio.eigene_domains", []) or []),
        "backup_pfad": settings.get("backup.pfad", "") or "",
        "export_firmenname": settings.get("export.firmenname", "") or "",
        "logo_vorhanden": settings.logo_pfad() is not None,
        "privates_telefon_zeigen": bool(settings.get("export.privates_telefon_zeigen", False)),
        "private_email_zeigen": bool(settings.get("export.private_email_zeigen", False)),
        "privatadresse_zeigen": bool(settings.get("export.privatadresse_zeigen", False)),
        "radicale_base_url": settings.get("radicale.base_url", "") or "",
        "radicale_addressbook_path": f"/{radicale.RADICALE_BENUTZER}/kontakte/",
        "radicale_username": radicale.RADICALE_BENUTZER,
        "radicale_password": settings.get("radicale.password", "") or "",
        "radicale_hostname": _hostname_local(),
        "ca_zertifikat_vorhanden": _ca_zertifikat_pfad().is_file(),
        "mail_host": settings.get("mail.host", "") or "",
        "mail_port": settings.get("mail.port", 993),
        "mail_username": settings.get("mail.username", "") or "",
        "mail_password": settings.get("mail.password", "") or "",
    })


@router.get("/einstellungen/logo")
def einstellungen_logo():
    pfad = settings.logo_pfad()
    if pfad is None:
        return Response(status_code=404)
    return FileResponse(pfad)


@router.post("/einstellungen/logo/entfernen")
def einstellungen_logo_entfernen():
    _logo_entfernen()
    return RedirectResponse(url="/einstellungen?gespeichert=1", status_code=303)


@router.get("/einstellungen/ca-zertifikat")
def einstellungen_ca_zertifikat():
    """Liefert die lokale CA aus, mit der Radicales TLS-Zertifikat signiert ist -
    Download-Weg fuer den Rollout auf weiteren Stationen: Datei laden, doppelklicken,
    im Schluesselbund auf "Immer vertrauen" setzen. Zuverlaessiger als sich auf den
    "Zertifikat vertrauen"-Dialog beim Account-Einrichten zu verlassen, da der
    macOS-Hintergrund-Sync-Dienst (contactsd/dataaccessd) eine dort erteilte
    per-Account-Ausnahme nicht immer uebernimmt - das fuehrt sonst zu genau den
    stillen Sync-Fehlern, die schon einmal aufgetreten sind."""
    pfad = _ca_zertifikat_pfad()
    if not pfad.is_file():
        return Response(status_code=404)
    return FileResponse(pfad, media_type="application/x-x509-ca-cert",
                         filename="rubrica-ca.pem")


@router.post("/einstellungen")
async def einstellungen_speichern(request: Request):
    form = await request.form()
    signatur_db_path = (form.get("archivio_signatur_db_path") or "").strip()
    try:
        min_mails = int(form.get("archivio_min_mails") or 2)
    except ValueError:
        min_mails = 2
    eigene_domains = [
        d.strip().lstrip("@").lower()
        for d in (form.get("archivio_eigene_domains") or "").split(",")
        if d.strip()
    ]
    backup_pfad = (form.get("backup_pfad") or "").strip()
    export_firmenname = (form.get("export_firmenname") or "").strip()
    radicale_base_url = (form.get("radicale_base_url") or "").strip()
    radicale_password = form.get("radicale_password") or ""
    mail_host = (form.get("mail_host") or "").strip()
    try:
        mail_port = int(form.get("mail_port") or 993)
    except ValueError:
        mail_port = 993
    mail_username = (form.get("mail_username") or "").strip()
    mail_password = form.get("mail_password") or ""

    logo = form.get("logo")
    if logo is not None and getattr(logo, "filename", ""):
        endung = Path(logo.filename).suffix.lower()
        if endung in LOGO_ERLAUBTE_ENDUNGEN:
            _logo_entfernen()
            ziel = settings.daten_verzeichnis() / f"{settings.LOGO_STAMM}{endung}"
            ziel.write_bytes(await logo.read())

    settings.save({
        "archivio": {"signatur_db_path": signatur_db_path, "min_mails": min_mails,
                     "eigene_domains": eigene_domains},
        "backup": {"pfad": backup_pfad},
        "radicale": {
            "base_url": radicale_base_url,
            "password": radicale_password,
        },
        "export": {
            "firmenname": export_firmenname,
            "privates_telefon_zeigen": form.get("privates_telefon_zeigen") is not None,
            "private_email_zeigen": form.get("private_email_zeigen") is not None,
            "privatadresse_zeigen": form.get("privatadresse_zeigen") is not None,
        },
        "mail": {
            "host": mail_host, "port": mail_port,
            "username": mail_username, "password": mail_password,
        },
    })

    # Das Radicale-Passwort in config.yaml ist nur die CLIENT-Seite (womit Rubrica pusht).
    # Die htpasswd-Datei, gegen die der Radicale-SERVER Logins prueft (Kontakte.app UND
    # Rubrica), muss mitgezogen werden - sonst schlaegt jeder Login fehl. Radicale liest
    # die Datei live neu ein, ein Neustart ist nicht noetig.
    if radicale_password:
        htpasswd.set_password(radicale.RADICALE_BENUTZER, radicale_password)

    return RedirectResponse(url="/einstellungen?gespeichert=1", status_code=303)


@router.post("/einstellungen/mail-test")
def einstellungen_mail_test():
    """Verbindungstest fuer das Mail-Eingang-Postfach - ein reiner Login+Logout,
    kein Abruf von Nachrichten (siehe mail_intake._client fuer die readonly-Garantie
    des eigentlichen Abrufs). Testet die zuletzt GESPEICHERTEN Zugangsdaten - erst
    "Speichern" klicken, falls die Felder gerade erst geaendert wurden (wie beim
    bestehenden "Jetzt synchronisieren"-Knopf fuer Radicale)."""
    if not mail_intake.konfiguriert():
        text = "Kein IMAP-Server konfiguriert (Host fehlt)."
    else:
        try:
            client = mail_intake._client()
            client.logout()
            text = "Verbindung erfolgreich."
        except Exception as exc:
            text = f"Verbindung fehlgeschlagen: {type(exc).__name__}: {exc}"
    return RedirectResponse(url=f"/einstellungen?mail={quote(text)}", status_code=303)


@router.post("/einstellungen/mail-pruefen")
def einstellungen_mail_pruefen():
    conn = get_connection()
    try:
        ergebnis = mail_intake.pruefe_mail_eingang(conn)
        if not ergebnis["aktiv"]:
            text = "Mail-Eingang nicht konfiguriert."
        else:
            text = (f"{ergebnis['gefunden']} Nachrichten geprüft, {ergebnis['neu']} neue "
                    f"Kontaktvorschläge angelegt.")
            if ergebnis["fehler"]:
                text += f" {ergebnis['fehler']} Nachrichten übersprungen (Fehler)."
    except Exception as exc:
        text = f"Prüfung fehlgeschlagen: {type(exc).__name__}: {exc}"
    finally:
        conn.close()
    return RedirectResponse(url=f"/einstellungen?mail={quote(text)}", status_code=303)


@router.post("/einstellungen/radicale-sync")
def einstellungen_radicale_sync():
    """Stoesst einen sichtbaren Vollabgleich zu Radicale an: pusht alle Kontakte/
    Ordner neu und entfernt verwaiste vCards. Nuetzlich, um Datensaetze
    nachzuziehen, deren automatischer Push frueher (still) fehlgeschlagen ist."""
    conn = get_connection()
    try:
        ergebnis = radicale.sync_alle(conn)
    finally:
        conn.close()

    if not ergebnis["aktiv"]:
        text = "Radicale nicht konfiguriert - Sync nicht möglich."
    else:
        text = (f"{ergebnis['kontakte']} Kontakte und {ergebnis['ordner']} Ordner synchronisiert, "
                f"{ergebnis['entfernt']} verwaiste Einträge entfernt.")
        if ergebnis["fehler"]:
            text += f" {len(ergebnis['fehler'])} Fehler (z. B. {ergebnis['fehler'][0]})."
    return RedirectResponse(url=f"/einstellungen?sync={quote(text)}", status_code=303)
