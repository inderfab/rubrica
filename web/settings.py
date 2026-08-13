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
from db import queries
from db.connection import get_connection
from sync import htpasswd, radicale
from web.shared import _hostname_local, templates

router = APIRouter()


def _ca_zertifikat_pfad() -> Path:
    return settings.daten_verzeichnis() / "radicale-tls" / "ca-cert.pem"


@router.get("/einstellungen")
def einstellungen_form(request: Request, gespeichert: str = "", sync: str = "", mail: str = "", reset: str = ""):
    # Abdeckung der Aenderungs-/Loescherkennung sichtbar machen: fehlt einem Kontakt
    # der Vergleichsstand, bleibt eine in Kontakte.app geloeschte oder geaenderte
    # Karte unbemerkt - eine stille Ursache, die man sonst nicht sieht.
    conn = get_connection()
    try:
        abdeckung = queries.ueberwachungs_abdeckung(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "abdeckung": abdeckung,
        "gespeichert": bool(gespeichert),
        "sync_ergebnis": sync,
        "mail_ergebnis": mail,
        "reset_ergebnis": reset,
        "archivio_signatur_db_path": settings.get("archivio.signatur_db_path", "") or "",
        "archivio_min_mails": settings.get("archivio.min_mails", 2),
        "archivio_eigene_domains": ", ".join(settings.get("archivio.eigene_domains", []) or []),
        "backup_pfad": settings.get("backup.pfad", "") or "",
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


_KATEGORIE_FELDER = {"telefon": settings.telefon_typen, "email": settings.email_typen,
                     "adresse": settings.adresse_typen}


def _kategorie_ansicht(conn, feld: str) -> dict:
    """Konfigurierte Kategorien (in ihrer Reihenfolge, mit Nutzungszahl) und daneben
    die Werte, die zwar im Bestand stehen, aber nicht zur Auswahl gehoeren - z.B.
    aus einem Import oder aus Kontakte.app. Nur so sieht man ueberhaupt, dass es
    sie gibt; im Kontaktformular selbst tauchen sie nur beim betroffenen Datensatz
    auf (siehe web/shared.py typ_optionen)."""
    bestand = {r["wert"]: r for r in queries.kategorie_werte_uebersicht(conn, feld)}
    konfiguriert = _KATEGORIE_FELDER[feld]()
    return {
        "konfiguriert": [
            {"wert": w, "anzahl": bestand.get(w, {}).get("anzahl", 0)} for w in konfiguriert
        ],
        "rest": [dict(r) for w, r in bestand.items() if w not in konfiguriert],
    }


def _betroffene_pushen(conn, kontakt_ids: list) -> None:
    """Die Kategorie steht als TYPE= in der vCard - ohne erneuten Push behielte
    Kontakte.app die alte Bezeichnung. Eine Umbenennung kann den halben Bestand
    treffen, deshalb eine gemeinsame Verbindung fuer den ganzen Batch (siehe
    web/shared.py: pro Kontakt eine eigene TLS-Verbindung war bei 1000+ Kontakten
    der groesste Teil der Laufzeit)."""
    eindeutige = sorted(set(kontakt_ids))
    if not eindeutige:
        return
    client = radicale._client()
    try:
        for kontakt_id in eindeutige:
            radicale.push_kontakt(conn, kontakt_id, client=client)
    finally:
        if client is not None:
            client.close()


@router.get("/einstellungen/kategorien")
def kategorien_uebersicht(request: Request, meldung: str = ""):
    """Verwaltung der Auswahllisten fuer Telefon- und E-Mail-Kategorien. Die Felder
    im Kontaktformular sind bewusst reine Dropdowns ohne Freitext (sonst entsteht
    wieder der Wildwuchs aus frei getippten Bezeichnungen) - neue Kategorien
    entstehen deshalb nur hier."""
    conn = get_connection()
    try:
        telefon = _kategorie_ansicht(conn, "telefon")
        email = _kategorie_ansicht(conn, "email")
        adresse = _kategorie_ansicht(conn, "adresse")
    finally:
        conn.close()
    return templates.TemplateResponse("kategorien.html", {
        "request": request, "telefon": telefon, "email": email, "adresse": adresse,
        "meldung": meldung,
    })


def _kategorien_uebernehmen(conn, feld: str, originale: list, namen: list) -> tuple:
    """Wertet die bearbeitete Liste aus: Reihenfolge und Bestand ergeben sich aus
    den Zeilen, eine geaenderte Bezeichnung benennt die Kategorie im ganzen Bestand
    mit um. Eine Kategorie, die noch an Eintraegen haengt, wird nicht entfernt -
    sonst haetten diese Eintraege eine Kategorie, die es nicht mehr zur Auswahl
    gibt. Zum Aufloesen erst umbenennen (das fuehrt sie in eine andere zusammen).
    Gibt (neue_liste, betroffene_kontakt_ids, hinweise) zurueck."""
    bestand = {r["wert"]: r["anzahl"] for r in queries.kategorie_werte_uebersicht(conn, feld)}
    vorher = _KATEGORIE_FELDER[feld]()
    neue_liste: list = []
    betroffene: list = []
    hinweise: list = []
    umbenannt = set()

    for original, name in zip(originale, namen):
        original, name = original.strip(), name.strip()
        if not name:
            continue  # Zeile geleert oder entfernt - Pruefung unten
        if original:
            umbenannt.add(original)
        if original and original != name:
            betroffene += queries.kategorie_global_umbenennen(conn, feld, original, name)
        if name not in neue_liste:
            neue_liste.append(name)

    for alt in vorher:
        if alt in umbenannt or alt in neue_liste or not bestand.get(alt):
            continue
        hinweise.append(
            f'„{alt}“ behalten – noch {bestand[alt]} Einträge. '
            f'Zum Auflösen in eine andere Kategorie umbenennen.'
        )
        neue_liste.append(alt)

    return neue_liste, betroffene, hinweise


@router.post("/einstellungen/kategorien")
async def kategorien_speichern(request: Request):
    form = await request.form()
    feld = (form.get("feld") or "").strip()
    if feld not in _KATEGORIE_FELDER:
        return RedirectResponse(url="/einstellungen/kategorien", status_code=303)

    conn = get_connection()
    try:
        neue_liste, betroffene, hinweise = _kategorien_uebernehmen(
            conn, feld, form.getlist("original"), form.getlist("name"),
        )
        if neue_liste:
            settings.save({"kategorien": {feld: neue_liste}})
        _betroffene_pushen(conn, betroffene)
    finally:
        conn.close()

    text = "Liste gespeichert."
    if betroffene:
        text += f" {len(set(betroffene))} Kontakte angepasst."
    if hinweise:
        text += " " + " ".join(hinweise)
    return RedirectResponse(url=f"/einstellungen/kategorien?meldung={quote(text)}", status_code=303)


@router.post("/einstellungen/kategorien/umbenennen")
async def kategorien_wert_umbenennen(request: Request):
    """Sortiert einen im Bestand vorhandenen Ausreisser in eine der konfigurierten
    Kategorien ein (oder benennt ihn frei um) - ohne die Auswahlliste zu aendern."""
    form = await request.form()
    feld = (form.get("feld") or "").strip()
    alter_wert = (form.get("alter_wert") or "").strip()
    neuer_wert = (form.get("neuer_wert") or "").strip()

    text = ""
    if feld in _KATEGORIE_FELDER and alter_wert and neuer_wert:
        conn = get_connection()
        try:
            betroffene = queries.kategorie_global_umbenennen(conn, feld, alter_wert, neuer_wert)
            _betroffene_pushen(conn, betroffene)
        finally:
            conn.close()
        text = f'„{alter_wert}“ → „{neuer_wert}“: {len(set(betroffene))} Kontakte angepasst.'
    return RedirectResponse(url=f"/einstellungen/kategorien?meldung={quote(text)}", status_code=303)


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
    radicale_base_url = (form.get("radicale_base_url") or "").strip()
    radicale_password = form.get("radicale_password") or ""
    mail_host = (form.get("mail_host") or "").strip()
    try:
        mail_port = int(form.get("mail_port") or 993)
    except ValueError:
        mail_port = 993
    mail_username = (form.get("mail_username") or "").strip()
    mail_password = form.get("mail_password") or ""

    # Firmenname, Logo und die sichtbaren Felder stehen bewusst auf der
    # Export-Seite (web/export.py) - sie wirken sich nur dort aus.
    settings.save({
        "archivio": {"signatur_db_path": signatur_db_path, "min_mails": min_mails,
                     "eigene_domains": eigene_domains},
        "backup": {"pfad": backup_pfad},
        "radicale": {
            "base_url": radicale_base_url,
            "password": radicale_password,
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
        text = mail_intake.pruefe_und_beschreibe(conn)
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


@router.post("/einstellungen/alle-kontakte-loeschen")
async def einstellungen_alle_kontakte_loeschen(request: Request):
    """Loescht ALLE Kontakte (und optional auch alle Ordner) - fuer einen sauberen
    Neustart vor einem erneuten Import (siehe queries.delete_alle_kontakte/
    delete_alle_projekte). Stoesst danach einen Radicale-Vollabgleich an, damit die
    jetzt verwaisten kontakt-*.vcf (und ggf. projekt-*.vcf) auch dort entfernt werden -
    sonst bleiben sie bis zum naechsten regulaeren Sync in Apple Kontakte sichtbar.
    Bei grossen Bestaenden (mehrere hundert/tausend Kontakte) kann dieser Vollabgleich
    selbst einige Minuten dauern (ein HTTP-DELETE pro verwaistem Eintrag)."""
    form = await request.form()
    auch_ordner = bool(form.get("auch_ordner"))

    conn = get_connection()
    try:
        anzahl = queries.delete_alle_kontakte(conn)
        ordner_anzahl = queries.delete_alle_projekte(conn) if auch_ordner else 0
        ergebnis = radicale.sync_alle(conn)
    finally:
        conn.close()

    text = f"{anzahl} Kontakte"
    if auch_ordner:
        text += f" und {ordner_anzahl} Ordner"
    text += " gelöscht."
    if ergebnis["aktiv"]:
        text += f" {ergebnis['entfernt']} verwaiste Einträge in Radicale entfernt."
    return RedirectResponse(url=f"/einstellungen?reset={quote(text)}", status_code=303)
