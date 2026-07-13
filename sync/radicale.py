"""Phase 2: schreibt bestaetigte Kontakte/Projekte als vCards nach Radicale (CardDAV).

Einweg-Synchronisation (App -> Radicale -> Apple Kontakte), nie umgekehrt - siehe
docs/konzept.md Abschnitt 5.1/5.2. Radicale wird nie gelesen, nur beschrieben.
Fehler (Radicale nicht erreichbar/nicht konfiguriert) duerfen die aufrufende
Web-Route nie unterbrechen: Rubrica bleibt auch ohne CardDAV-Sync voll funktionsfaehig.
"""
from __future__ import annotations

import logging
import re
import sqlite3

import httpx

from config import settings
from db import queries

log = logging.getLogger(__name__)


def _escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _sichere_utf8_grenze(daten: bytes, pos: int) -> int:
    """Verschiebt eine Byte-Schnittstelle zurueck, falls sie mitten in einer
    UTF-8-Mehrbyte-Sequenz (Fortsetzungsbyte 10xxxxxx) liegen wuerde."""
    while pos > 0 and (daten[pos] & 0xC0) == 0x80:
        pos -= 1
    return pos


def _fold(zeile: str) -> str:
    """RFC-6350-Zeilenfaltung: Zeilen ueber 75 Oktette werden mit CRLF + Leerzeichen
    fortgesetzt. Manche CardDAV-Server (u.a. Radicale) lehnen unzulaessig lange,
    ungefaltete Zeilen mit 400 Bad Request ab (in der Praxis beobachtet bei
    Kontakten mit vielen Telefonnummern/Adressfeldern)."""
    daten = zeile.encode("utf-8")
    if len(daten) <= 75:
        return zeile
    teile = []
    rest = daten
    limit = 75
    while len(rest) > limit:
        grenze = _sichere_utf8_grenze(rest, limit)
        teile.append(rest[:grenze])
        rest = rest[grenze:]
        limit = 74  # Folgezeilen: 1 Oktett fuer das fuehrende Leerzeichen abziehen
    teile.append(rest)
    return "\r\n ".join(t.decode("utf-8") for t in teile)


def kontakt_zu_vcard(kontakt: dict) -> str:
    """Baut eine vCard 3.0 aus einem queries.get_kontakt()-Dict."""
    zeilen = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"UID:kontakt-{kontakt['id']}",
        f"N:{_escape(kontakt['nachname'])};{_escape(kontakt['vorname'])};;;",
        f"FN:{_escape(kontakt['vorname'])} {_escape(kontakt['nachname'])}".strip(),
    ]
    if kontakt.get("firma"):
        zeilen.append(f"ORG:{_escape(kontakt['firma'])}")
    if kontakt.get("rolle"):
        zeilen.append(f"TITLE:{_escape(kontakt['rolle'])}")
    if kontakt.get("kategorie"):
        zeilen.append(f"CATEGORIES:{_escape(kontakt['kategorie'])}")
    for tel in kontakt.get("telefonnummern", []):
        zeilen.append(f"TEL;TYPE={_escape(tel['typ']).upper()}:{tel['nummer']}")
    for mail in kontakt.get("emails", []):
        zeilen.append(f"EMAIL;TYPE={_escape(mail['typ']).upper()}:{mail['email']}")
    for adr in kontakt.get("adressen", []):
        zeilen.append(
            f"ADR;TYPE={_escape(adr['typ']).upper()}:;;{_escape(adr['strasse'])};"
            f"{_escape(adr['ort'])};{_escape(adr['region'])};{_escape(adr['plz'])};{_escape(adr['land'])}"
        )
    for url in kontakt.get("urls", []):
        zeilen.append(f"URL;TYPE={_escape(url['typ']).upper()}:{url['url']}")
    if kontakt.get("notizen"):
        zeilen.append(f"NOTE:{_escape(kontakt['notizen'])}")
    zeilen.append("END:VCARD")
    return "\r\n".join(_fold(z) for z in zeilen) + "\r\n"


def projekt_zu_gruppen_vcard(projekt: dict, mitglieder_ids: list) -> str:
    """Baut eine Apple-Gruppen-vCard (proprietaeres X-ADDRESSBOOKSERVER-Format)."""
    zeilen = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"UID:projekt-{projekt['id']}",
        f"FN:{_escape(projekt['name'])}",
        f"N:{_escape(projekt['name'])};;;;",
        "X-ADDRESSBOOKSERVER-KIND:group",
    ]
    for kontakt_id in mitglieder_ids:
        zeilen.append(f"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:kontakt-{kontakt_id}")
    zeilen.append("END:VCARD")
    return "\r\n".join(_fold(z) for z in zeilen) + "\r\n"


def _tls_verify():
    """TLS-Pruefung fuer den Push zum eigenen Radicale. Wichtig: Rubrica pusht
    immer an das eigene Radicale (in der Praxis 127.0.0.1, Loopback). Dessen
    Zertifikat ist von einer lokal erzeugten CA signiert, die NICHT im certifi-
    Trust-Store von httpx liegt - `verify=True` (Default) bricht deshalb jeden
    Push mit einem Zertifikatsfehler ab, und zwar STILL, weil Sync-Fehler die
    Web-Route nie unterbrechen duerfen. Genau das liess neu erstellte Kontakte
    lokal erscheinen, aber nie bei Radicale/Apple Kontakte ankommen.

    - Verify ausdruecklich abgeschaltet (verify_ssl=false) -> keine Pruefung.
    - Sonst gegen die lokale CA-Datei pruefen, falls vorhanden (sicher + funktioniert).
    - Sonst (Pruefung gewuenscht, aber keine lokale CA auffindbar) auf Loopback
      ohne Pruefung, statt den Push scheitern zu lassen - 127.0.0.1 ist nicht
      abhoerbar, echte Sicherheit geht dadurch nicht verloren."""
    if not settings.get("radicale.verify_ssl", True):
        return False
    ca_cert = settings.daten_verzeichnis() / "radicale-tls" / "ca-cert.pem"
    if ca_cert.is_file():
        return str(ca_cert)
    return False


def _client() -> httpx.Client | None:
    """Kein separater An/Aus-Schalter: Sync ist immer aktiv, sobald eine base_url
    konfiguriert ist (siehe config.yaml.example) - ein vergessener/versehentlich
    gesetzter "enabled: false"-Schalter hat schon zu Verwirrung gefuehrt, weil
    Kontakte lokal geloescht wurden, der Push zu Radicale aber nie versucht wurde."""
    base_url = settings.get("radicale.base_url", "")
    if not base_url:
        return None
    return httpx.Client(
        base_url=base_url.rstrip("/") + settings.get("radicale.addressbook_path", "/"),
        auth=(settings.get("radicale.username", ""), settings.get("radicale.password", "")),
        verify=_tls_verify(),
        timeout=5.0,
    )


_MKCOL_BODY = """<?xml version="1.0" encoding="utf-8"?>
<create xmlns="DAV:" xmlns:CR="urn:ietf:params:xml:ns:carddav">
  <set>
    <prop>
      <resourcetype><collection/><CR:addressbook/></resourcetype>
      <displayname>Rubrica</displayname>
    </prop>
  </set>
</create>"""


def _put(pfad: str, vcard: str) -> bool:
    """Gibt True bei Erfolg zurueck, False bei uebersprungenem/fehlgeschlagenem Push.
    Fehler werden geloggt, aber nie geworfen (Sync darf die Web-Route nie unterbrechen)."""
    client = _client()
    if client is None:
        log.debug("Radicale-Sync deaktiviert, ueberspringe PUT %s", pfad)
        return False
    try:
        with client:
            resp = client.put(pfad, content=vcard.encode("utf-8"),
                               headers={"Content-Type": "text/vcard; charset=utf-8"})
            if resp.status_code == 409:
                # Adressbuch-Collection existiert noch nicht - einmalig anlegen und erneut versuchen.
                mkcol = client.request("MKCOL", "", content=_MKCOL_BODY,
                                        headers={"Content-Type": "application/xml"})
                if mkcol.status_code not in (201, 405):
                    mkcol.raise_for_status()
                resp = client.put(pfad, content=vcard.encode("utf-8"),
                                   headers={"Content-Type": "text/vcard; charset=utf-8"})
            resp.raise_for_status()
            return True
    except httpx.HTTPError as exc:
        log.warning("Radicale-Sync fehlgeschlagen fuer %s: %s", pfad, exc)
        return False


def _delete(pfad: str) -> bool:
    client = _client()
    if client is None:
        log.debug("Radicale-Sync deaktiviert, ueberspringe DELETE %s", pfad)
        return False
    try:
        with client:
            resp = client.delete(pfad)
            if resp.status_code not in (204, 404):
                resp.raise_for_status()
            return True
    except httpx.HTTPError as exc:
        log.warning("Radicale-Loeschung fehlgeschlagen fuer %s: %s", pfad, exc)
        return False


def _remote_vcf_namen() -> list:
    """Listet die vcf-Dateinamen im Radicale-Adressbuch per PROPFIND (Tiefe 1).
    Bewusst tolerantes Regex statt XML-Parser: es interessieren nur die von Rubrica
    selbst vergebenen, streng gemusterten Namen (kontakt-N.vcf / projekt-N.vcf)."""
    client = _client()
    if client is None:
        return []
    try:
        with client:
            resp = client.request("PROPFIND", "", headers={"Depth": "1"})
            if resp.status_code >= 400:
                return []
            return re.findall(r"(kontakt-\d+\.vcf|projekt-\d+\.vcf)", resp.text)
    except httpx.HTTPError as exc:
        log.warning("Radicale-PROPFIND fehlgeschlagen: %s", exc)
        return []


def push_kontakt(conn: sqlite3.Connection, kontakt_id: int) -> bool:
    kontakt = queries.get_kontakt(conn, kontakt_id)
    if kontakt is None:
        return False
    return _put(f"kontakt-{kontakt_id}.vcf", kontakt_zu_vcard(kontakt))


def delete_kontakt(kontakt_id: int) -> bool:
    return _delete(f"kontakt-{kontakt_id}.vcf")


def push_projekt(conn: sqlite3.Connection, projekt_id: int) -> bool:
    row = conn.execute("SELECT * FROM projekte WHERE id = ?", (projekt_id,)).fetchone()
    if row is None:
        return False
    projekt = dict(row)
    mitglieder_ids = [
        r["kontakt_id"] for r in conn.execute(
            "SELECT kontakt_id FROM kontakte_projekte WHERE projekt_id = ? ORDER BY kontakt_id", (projekt_id,)
        )
    ]
    return _put(f"projekt-{projekt_id}.vcf", projekt_zu_gruppen_vcard(projekt, mitglieder_ids))


def delete_projekt(projekt_id: int) -> bool:
    return _delete(f"projekt-{projekt_id}.vcf")


def sync_alle(conn: sqlite3.Connection) -> dict:
    """Vollabgleich zu Radicale, mit sichtbarer Rueckmeldung fuer die UI:
      1. Entfernt verwaiste vCards (in Radicale vorhanden, aber nicht mehr in der DB -
         z.B. frueher geloeschte Kontakte, deren Delete-Push damals fehlschlug).
      2. Pusht alle aktuellen Kontakte und Ordner neu.
    Gibt eine Zusammenfassung zurueck (Anzahlen + erste Fehlermeldung), damit der
    Nutzer im Gegensatz zum sonst stillen Sync sieht, ob es geklappt hat."""
    if _client() is None:
        return {"aktiv": False, "kontakte": 0, "ordner": 0, "entfernt": 0,
                "fehler": ["Kein Radicale-Server konfiguriert (Server-Adresse leer)."]}

    kontakt_ids = [row["id"] for row in conn.execute("SELECT id FROM kontakte")]
    projekt_ids = [row["id"] for row in conn.execute("SELECT id FROM projekte")]
    gueltig = {f"kontakt-{i}.vcf" for i in kontakt_ids} | {f"projekt-{i}.vcf" for i in projekt_ids}

    fehler = []
    entfernt = 0
    for name in set(_remote_vcf_namen()):
        if name not in gueltig:
            if _delete(name):
                entfernt += 1
            else:
                fehler.append(f"Konnte verwaiste {name} nicht entfernen")

    kontakte_ok = 0
    for kontakt_id in kontakt_ids:
        if push_kontakt(conn, kontakt_id):
            kontakte_ok += 1
        elif len(fehler) < 5:
            fehler.append(f"Push von kontakt-{kontakt_id} fehlgeschlagen")

    ordner_ok = 0
    for projekt_id in projekt_ids:
        if push_projekt(conn, projekt_id):
            ordner_ok += 1
        elif len(fehler) < 5:
            fehler.append(f"Push von projekt-{projekt_id} fehlgeschlagen")

    return {"aktiv": True, "kontakte": kontakte_ok, "ordner": ordner_ok,
            "entfernt": entfernt, "fehler": fehler}
