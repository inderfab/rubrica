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

# Fest verdrahtet statt konfigurierbar (frueher aus dem macOS-Benutzernamen der
# jeweiligen Maschine abgeleitet, siehe config.yaml.example vor 2026-07-14): unter
# Radicales "owner_only"-Rechtemodell muessen Benutzername und Adressbuch-Pfad
# immer zusammenpassen (Pfad muss mit "/{username}/" beginnen). Ein frei
# konfigurierbarer Wert fuehrte bereits zweimal zu einem stillen Sync-Ausfall
# (Aendern nur eines der beiden Werte, bzw. ein Maschinen-Benutzername, der vom
# gewuenschten CardDAV-Konto-Namen abwich) - ein einziger fester Wert fuer alle
# Installationen macht diese Fehlerklasse strukturell unmoeglich. Produktbezogen
# statt an ein bestimmtes Buero gebunden (2026-07-14 umbenannt vom vorherigen
# buerospezifischen Wert, siehe scripts/migrate-radicale-user.sh fuer bereits
# laufende Installationen).
RADICALE_BENUTZER = "rubrica"

# Text des zuletzt aufgetretenen Sync-Fehlers (z.B. "401 Unauthorized",
# "SSLError ..."). Sync-Fehler werden sonst still verschluckt; sync_alle() gibt
# diesen Text mit zurueck, damit die manuelle "Jetzt synchronisieren"-Aktion
# einen konkreten Grund anzeigen kann statt nur "fehlgeschlagen".
_letzter_fehler = ""


def _merke_fehler(exc: Exception) -> None:
    global _letzter_fehler
    _letzter_fehler = f"{type(exc).__name__}: {exc}"


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


def _client() -> httpx.Client | None:
    """Kein separater An/Aus-Schalter: Sync ist immer aktiv, sobald eine base_url
    konfiguriert ist (siehe config.yaml.example) - ein vergessener/versehentlich
    gesetzter "enabled: false"-Schalter hat schon zu Verwirrung gefuehrt, weil
    Kontakte lokal geloescht wurden, der Push zu Radicale aber nie versucht wurde.

    TLS-Pruefung bewusst AUS (verify=False): Rubrica pusht immer an das eigene
    Radicale auf Loopback (127.0.0.1). Dessen selbst erzeugtes Zertifikat ist von
    einer certifi-unbekannten CA signiert UND deckt je nach Erstellungszeit 127.0.0.1
    gar nicht im SAN ab (aeltere Installationen nur den Hostnamen) - eine Pruefung
    scheiterte deshalb wiederholt und liess den Push STILL fehlschlagen (Sync-Fehler
    unterbrechen die Web-Route nie). Auf 127.0.0.1 bringt die Pruefung ohnehin keinen
    Sicherheitsgewinn (nicht abhoerbar), darum ganz ohne. Kontakte.app (macOS) ist
    davon unberuehrt - es prueft ueber den System-Schluesselbund gegen den Hostnamen."""
    base_url = settings.get("radicale.base_url", "")
    if not base_url:
        return None
    return httpx.Client(
        base_url=base_url.rstrip("/") + f"/{RADICALE_BENUTZER}/kontakte/",
        auth=(RADICALE_BENUTZER, settings.get("radicale.password", "")),
        verify=False,
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


def _put(pfad: str, vcard: str, client: "httpx.Client | None" = None) -> bool:
    """Gibt True bei Erfolg zurueck, False bei uebersprungenem/fehlgeschlagenem Push.
    Fehler werden geloggt, aber nie geworfen (Sync darf die Web-Route nie unterbrechen).
    `client`: optionaler, wiederverwendeter Client (siehe sync_alle) - dann bleibt die
    Verbindung offen, statt pro Aufruf neu (mit TLS-Handshake) aufgebaut zu werden."""
    eigener = client is None
    if eigener:
        client = _client()
    if client is None:
        log.debug("Radicale-Sync deaktiviert, ueberspringe PUT %s", pfad)
        return False
    try:
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
        _merke_fehler(exc)
        return False
    finally:
        if eigener:
            client.close()


def _delete(pfad: str, client: "httpx.Client | None" = None) -> bool:
    eigener = client is None
    if eigener:
        client = _client()
    if client is None:
        log.debug("Radicale-Sync deaktiviert, ueberspringe DELETE %s", pfad)
        return False
    try:
        resp = client.delete(pfad)
        if resp.status_code not in (204, 404):
            resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.warning("Radicale-Loeschung fehlgeschlagen fuer %s: %s", pfad, exc)
        _merke_fehler(exc)
        return False
    finally:
        if eigener:
            client.close()


def _remote_vcf_namen(client: "httpx.Client | None" = None) -> list:
    """Listet die vcf-Dateinamen im Radicale-Adressbuch per PROPFIND (Tiefe 1).
    Bewusst tolerantes Regex statt XML-Parser: es interessieren nur die von Rubrica
    selbst vergebenen, streng gemusterten Namen (kontakt-N.vcf / projekt-N.vcf)."""
    eigener = client is None
    if eigener:
        client = _client()
    if client is None:
        return []
    try:
        resp = client.request("PROPFIND", "", headers={"Depth": "1"})
        if resp.status_code >= 400:
            return []
        return re.findall(r"(kontakt-\d+\.vcf|projekt-\d+\.vcf)", resp.text)
    except httpx.HTTPError as exc:
        log.warning("Radicale-PROPFIND fehlgeschlagen: %s", exc)
        _merke_fehler(exc)
        return []
    finally:
        if eigener:
            client.close()


def gruppen_mitglieder_auf_server(projekt_id: int,
                                   client: "httpx.Client | None" = None) -> "set[int] | None":
    """Liest die kontakt_id der Mitglieder aus der Gruppen-vCard auf Radicale.
    None, wenn die vCard nicht existiert, nicht lesbar ist oder kein Client
    vorhanden ist - der Aufrufer darf daraus NIE "keine Mitglieder" ableiten,
    sonst gilt ein fehlgeschlagener Abruf als "alle entfernt"."""
    if client is None:
        return None
    try:
        resp = client.get(f"projekt-{projekt_id}.vcf")
    except httpx.HTTPError as exc:
        log.warning("Gruppen-vCard projekt-%s konnte nicht gelesen werden: %s", projekt_id, exc)
        return None
    if resp.status_code != 200:
        return None
    return {int(i) for i in re.findall(r"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:kontakt-(\d+)", resp.text)}


def _zusammengefuehrte_mitglieder(conn: sqlite3.Connection, projekt_id: int,
                                   db_ids: set, client: "httpx.Client | None") -> set:
    """Fuehrt den Datenbankstand mit dem zusammen, was seit dem letzten eigenen Push
    auf dem Server passiert ist (jemand hat in Kontakte.app einen Kontakt in diese
    Gruppe gezogen oder daraus entfernt).

    Ohne dieses Lesen-vor-Schreiben ueberschreibt jeder Push die Gruppen-vCard blind
    mit dem Datenbankstand - eine noch nicht eingelesene Aenderung eines Kollegen ist
    dann unwiederbringlich weg, und zwar lautlos. Das trat nachweislich auf: Kollege
    fuegt B hinzu, jemand anderes fuegt im Browser C hinzu, B verschwindet.

    Der Schnappschuss (projekte.zuletzt_gepushte_mitglieder) trennt dabei "vom Client
    geaendert" von "unser eigener Stand": alles, worin der Server vom Schnappschuss
    abweicht, kann nur von aussen kommen. Ohne Schnappschuss (nie gepusht, Altbestand)
    bleibt es beim reinen Datenbankstand - jede andere Annahme waere Spekulation."""
    schnappschuss = queries.hole_gepushte_mitglieder(conn, projekt_id)
    if schnappschuss is None:
        return db_ids
    server = gruppen_mitglieder_auf_server(projekt_id, client=client)
    if server is None:
        return db_ids

    hinzugefuegt = server - schnappschuss
    entfernt = schnappschuss - server
    if hinzugefuegt:
        # Die vCard kann auf einen zwischenzeitlich geloeschten Kontakt zeigen.
        vorhanden = {
            r["id"] for r in conn.execute(
                "SELECT id FROM kontakte WHERE id IN (%s)" % ",".join("?" * len(hinzugefuegt)),
                tuple(sorted(hinzugefuegt)),
            )
        }
        hinzugefuegt &= vorhanden
    return (db_ids | hinzugefuegt) - entfernt


def push_kontakt(conn: sqlite3.Connection, kontakt_id: int,
                 client: "httpx.Client | None" = None) -> bool:
    kontakt = queries.get_kontakt(conn, kontakt_id)
    if kontakt is None:
        return False
    vcard = kontakt_zu_vcard(kontakt)
    erfolg = _put(f"kontakt-{kontakt_id}.vcf", vcard, client=client)
    if erfolg:
        # Nur nach bestaetigtem Push festhalten - ein fehlgeschlagener Push wuerde sonst
        # einen Vergleichsstand setzen, den es auf dem Server gar nicht gibt, und die
        # naechste Aenderungserkennung schriebe die Differenz faelschlich einem
        # Mac-Client zu (siehe kontakte_app_intake.pruefe_kontakt_aenderungen).
        queries.setze_gepushte_vcard(conn, kontakt_id, vcard)
    return erfolg


def delete_kontakt(kontakt_id: int) -> bool:
    return _delete(f"kontakt-{kontakt_id}.vcf")


def _ist_z_ordner(name: str) -> bool:
    """Ordner mit fuehrendem 'Z' (z.B. "Z1_Weihnachten 2013") sind interne
    Sammelordner, die zwar in der Web-Oberflaeche editierbar bleiben, aber nie als
    Apple-Gruppe auf die Geraete synchronisiert werden sollen (Nutzer-Vorgabe) -
    Fallunterscheidung bewusst grosszuegig (nur der erste Buchstabe zaehlt)."""
    return (name or "").strip().lower().startswith("z")


def push_projekt(conn: sqlite3.Connection, projekt_id: int,
                 client: "httpx.Client | None" = None) -> bool:
    row = conn.execute("SELECT * FROM projekte WHERE id = ?", (projekt_id,)).fetchone()
    if row is None:
        return False
    projekt = dict(row)
    if _ist_z_ordner(projekt["name"]):
        # Aktiv loeschen statt nur zu ueberspringen: Regression (Nutzer-Feedback) - ein
        # Ordner, der VOR der Umbenennung ins Archiv (Z-Praefix) bereits unter dem alten
        # Namen an Radicale gepusht war, blieb dort sonst unveraendert liegen, bis der
        # naechste manuelle Vollabgleich (sync_alle) die verwaiste vCard entfernte. Ein
        # reiner "return True" ohne Aktion propagiert die Umbenennung nicht sofort - eine
        # aktive DELETE-Anfrage schon (404 auf eine nie gepushte Z-Ordner-vCard gilt in
        # _delete() bereits als Erfolg, daher unschaedlich fuer schon immer Z-benannte Ordner).
        # Schnappschuss loeschen: die vCard existiert nicht mehr, ein Abgleich haette
        # keinen Bezugspunkt (siehe queries.setze_gepushte_mitglieder).
        queries.setze_gepushte_mitglieder(conn, projekt_id, None)
        return _delete(f"projekt-{projekt_id}.vcf", client=client)
    db_ids = {
        r["kontakt_id"] for r in conn.execute(
            "SELECT kontakt_id FROM kontakte_projekte WHERE projekt_id = ?", (projekt_id,)
        )
    }
    # Lesen vor Schreiben: erst zusammenfuehren, was seit dem letzten eigenen Push von
    # einem Mac-Client kam, dann schreiben (siehe _zusammengefuehrte_mitglieder).
    eigener = client is None
    if eigener:
        client = _client()
    try:
        soll = _zusammengefuehrte_mitglieder(conn, projekt_id, db_ids, client)
        if soll != db_ids:
            # Datenbank an den zusammengefuehrten Stand angleichen, sonst wuerde der
            # naechste Push die fremde Aenderung erneut verwerfen.
            queries.setze_kontakt_projekt_zuordnungen(conn, projekt_id, soll)
        mitglieder_ids = sorted(soll)
        erfolg = _put(f"projekt-{projekt_id}.vcf",
                       projekt_zu_gruppen_vcard(projekt, mitglieder_ids), client=client)
        if erfolg:
            # Nur nach einem BESTAETIGTEN Push festhalten, was auf dem Server steht - sonst
            # wuerde ein fehlgeschlagener Push einen falschen Referenzpunkt setzen und der
            # naechste Abgleich die Differenz faelschlich einem Mac-Client zuschreiben
            # (siehe kontakte_app_intake.pruefe_ordner_mitgliedschaften).
            queries.setze_gepushte_mitglieder(conn, projekt_id, mitglieder_ids)
        return erfolg
    finally:
        if eigener and client is not None:
            client.close()


def delete_projekt(projekt_id: int) -> bool:
    return _delete(f"projekt-{projekt_id}.vcf")


def push_kontakt_mit_ordnern(conn: sqlite3.Connection, kontakt_id: int,
                              client: "httpx.Client | None" = None) -> None:
    """Pusht einen Kontakt und alle seine zugeordneten Ordner - gemeinsame Nachbereitung
    nach jedem direkten Anlegen/Mergen (Import, Archivio-Uebernahme), da ein Kontakt
    dabei haeufig zugleich einem (neuen oder bestehenden) Ordner zugewiesen wird.
    `client`: optionaler, wiederverwendeter Client fuer Batch-Aufrufe (siehe
    web/shared.py, web/imports.py) - ohne das baut jeder einzelne Aufruf eine eigene
    TLS-Verbindung auf, was bei grossen Imports (1000+ Kontakte) den Grossteil der
    Laufzeit ausmachte (derselbe Grund wie in sync_alle() weiter unten dokumentiert)."""
    eigener = client is None
    if eigener:
        client = _client()
    if client is None:
        return
    try:
        push_kontakt(conn, kontakt_id, client=client)
        kontakt = queries.get_kontakt(conn, kontakt_id)
        if kontakt is None:
            return
        for p in kontakt["projekte"]:
            push_projekt(conn, p["id"], client=client)
    finally:
        if eigener:
            client.close()


def sync_alle(conn: sqlite3.Connection) -> dict:
    """Vollabgleich zu Radicale, mit sichtbarer Rueckmeldung fuer die UI:
      0. Liest zuerst in Kontakte.app geaenderte Ordner-Zuordnungen ein.
      1. Entfernt verwaiste vCards (in Radicale vorhanden, aber nicht mehr in der DB -
         z.B. frueher geloeschte Kontakte, deren Delete-Push damals fehlschlug).
      2. Pusht alle aktuellen Kontakte und Ordner neu.
    Gibt eine Zusammenfassung zurueck (Anzahlen + erste Fehlermeldung), damit der
    Nutzer im Gegensatz zum sonst stillen Sync sieht, ob es geklappt hat.

    Schritt 0 muss VOR dem Pushen laufen: Schritt 2 baut jede Gruppen-vCard komplett
    aus kontakte_projekte neu auf und wuerde eine in Kontakte.app vorgenommene, noch
    nicht eingelesene Zuordnung sonst lautlos verwerfen - ausgerechnet der Knopf
    "Jetzt alles neu synchronisieren" waere damit ein Datenverlust-Werkzeug."""
    global _letzter_fehler
    _letzter_fehler = ""
    client = _client()
    if client is None:
        return {"aktiv": False, "kontakte": 0, "ordner": 0, "entfernt": 0,
                "fehler": ["Kein Radicale-Server konfiguriert (Server-Adresse leer)."]}

    # Import bewusst lokal: kontakte_app_intake importiert seinerseits dieses Modul,
    # ein Import auf Modulebene waere zirkulaer.
    import kontakte_app_intake
    try:
        kontakte_app_intake.pruefe_ordner_mitgliedschaften(conn, client=client)
    except Exception as exc:  # darf den Vollabgleich nie verhindern
        log.warning("Ordner-Abgleich vor dem Vollabgleich fehlgeschlagen: %s", exc)
    try:
        # Ebenfalls zwingend VOR dem Pushen: Schritt 2 ueberschreibt jede Kontakt-vCard
        # mit dem Datenbankstand und wuerde eine in Kontakte.app vorgenommene, noch
        # nicht erfasste Feldaenderung sonst spurlos verwerfen.
        kontakte_app_intake.pruefe_kontakt_aenderungen(conn, client=client)
    except Exception as exc:
        log.warning("Aenderungserkennung vor dem Vollabgleich fehlgeschlagen: %s", exc)

    # Eine Verbindung fuer den gesamten Lauf wiederverwenden: bei ~1500 Datensaetzen
    # spart das ~1500 TLS-Handshakes/Verbindungsaufbauten (der langsamste Teil des
    # Voll-Syncs). Die serverseitige bcrypt-Passwortpruefung pro Anfrage bleibt.
    try:
        kontakt_ids = [row["id"] for row in conn.execute("SELECT id FROM kontakte")]
        projekt_rows = [dict(r) for r in conn.execute("SELECT id, name FROM projekte")]
        # Z-Ordner werden nie synchronisiert (siehe push_projekt/_ist_z_ordner) - hier
        # zusaetzlich aus "gueltig" ausgeschlossen, damit eine schon vorher (vor
        # Einfuehrung dieser Regel) gepushte Z-Ordner-vCard hier als verwaist erkannt
        # und automatisch entfernt wird, ohne eigenen Loesch-Code.
        sync_projekt_ids = [r["id"] for r in projekt_rows if not _ist_z_ordner(r["name"])]
        gueltig = {f"kontakt-{i}.vcf" for i in kontakt_ids} | {f"projekt-{i}.vcf" for i in sync_projekt_ids}

        fehler = []
        entfernt = 0
        for name in set(_remote_vcf_namen(client=client)):
            if name not in gueltig:
                if _delete(name, client=client):
                    entfernt += 1
                else:
                    fehler.append(f"Konnte verwaiste {name} nicht entfernen")

        kontakte_ok = 0
        for kontakt_id in kontakt_ids:
            if push_kontakt(conn, kontakt_id, client=client):
                kontakte_ok += 1
            elif len(fehler) < 5:
                fehler.append(f"Push von kontakt-{kontakt_id} fehlgeschlagen")

        ordner_ok = 0
        for projekt_id in sync_projekt_ids:
            if push_projekt(conn, projekt_id, client=client):
                ordner_ok += 1
            elif len(fehler) < 5:
                fehler.append(f"Push von projekt-{projekt_id} fehlgeschlagen")
    finally:
        client.close()

    # Den konkreten letzten Fehlergrund (z.B. "401 Unauthorized") voranstellen,
    # damit die UI-Rueckmeldung nicht nur "fehlgeschlagen", sondern das Warum zeigt.
    if fehler and _letzter_fehler:
        fehler.insert(0, f"Grund: {_letzter_fehler}")

    return {"aktiv": True, "kontakte": kontakte_ok, "ordner": ordner_ok,
            "entfernt": entfernt, "fehler": fehler}
