"""Erkennt Kontakte UND Ordner, die direkt in Kontakte.app (auf irgendeinem ueber
CardDAV verbundenen Mac) angelegt wurden, statt in Rubrica selbst - Radicales
"owner_only"-Rechtemodell (siehe sync/radicale.py) kann nicht zwischen Rubricas
eigenem Push und einem direkt schreibenden Mac-Client unterscheiden, jeder
verbundene Mac kann also technisch beliebige vCards in derselben Collection
anlegen/aendern/loeschen (bisher ungewollter Nebeneffekt, siehe den "Neue
Liste"-Vorfall in docs/CHANGELOG-INTERN.md). Dieses Modul macht daraus einen
bewussten dritten Erfassungskanal (neben manueller Neuanlage und Mail-Eingang,
siehe mail_intake.py, dessen Struktur hier bewusst gespiegelt wird): jede
fremde vCard (Name entspricht nicht dem Muster kontakt-N.vcf/projekt-N.vcf,
das nur Rubricas eigene Pushes tragen, siehe sync/radicale.py) erzeugt einen
offenen Eintrag in vorschlaege, der erst im Buero manuell bestaetigt wird
(siehe web/vorschlaege.py) - nie automatisch uebernommen. Ein Vorschlag mit
rohdaten.typ == "ordner" steht fuer eine fremde Gruppen-Neuanlage (z.B. "Neue
Liste"), alle anderen fuer einen fremden Kontakt.

Dies ist die einzige bewusste Ausnahme von "Radicale wird nie gelesen, nur
beschrieben" (siehe sync/radicale.py-Modul-Docstring): dieses Modul liest
gezielt (PROPFIND + GET), schreibt aber nichts aus eigenem Antrieb - das
Loeschen der fremden vCard erfolgt erst nach expliziter Bestaetigung im Buero
(siehe web/vorschlaege.py), damit dort ein saubere eigene vCard (kontakt-N.vcf
bzw. projekt-N.vcf) ohne Dublette entsteht.

Mitgliedschafts-Erkennung ist zweiseitig ("wenn moeglich", Nutzer-Vorgabe):
1. Ein fremder KONTAKT, der einem in Rubrica bereits bestehenden Ordner
   hinzugefuegt wurde, wird erkannt, indem jede eigene projekt-N.vcf auf
   X-ADDRESSBOOKSERVER-MEMBER-Zeilen mit der Apple-UID des fremden Kontakts
   gescannt wird (siehe _projekt_mitgliedschaften) - landet als
   erkannte_ordner_ids auf dem Kontakt-Vorschlag.
2. Ein fremder ORDNER (Gruppen-Neuanlage) wird selbst zum Vorschlag; dessen
   Mitgliederliste (Apple-UIDs) wird erst beim Bestaetigen (nicht schon bei
   der Erkennung) gegen bereits existierende Rubrica-Kontakte aufgeloest
   (siehe bestaetige_ordner_vorschlag) - Mitglieder, deren eigener
   Kontakt-Vorschlag noch nicht bestaetigt ist, werden dabei NICHT
   nachtraeglich verknuepft und muessen im Buero danach manuell per Drag&Drop
   ergaenzt werden.
Race bewusst in Kauf genommen: pusht Rubrica einen bereits bestehenden Ordner
(push_projekt) neu, BEVOR ein Scan laeuft, baut das die Mitgliederliste
komplett aus der eigenen kontakte_projekte-Tabelle neu auf und ueberschreibt
damit eine gerade erst in Kontakte.app hinzugefuegte Mitgliedschaft, ohne dass
dieses Modul das noch sehen koennte.
"""
from __future__ import annotations

import re

from db import queries
from importer.vcard import finde_match, parse_vcf
from sync import radicale

_EIGENES_MUSTER = re.compile(r"^(kontakt|projekt)-\d+\.vcf$")
_GRUPPEN_MUSTER = re.compile(r"X-ADDRESSBOOKSERVER-KIND:\s*group", re.IGNORECASE)


def konfiguriert() -> bool:
    return bool(radicale.settings.get("radicale.base_url", ""))


def _fremde_vcf_namen(client) -> list[str]:
    """Alle .vcf-Ressourcennamen im Adressbuch (PROPFIND, Tiefe 1), gefiltert auf
    alles, was NICHT Rubricas eigenem Namensmuster entspricht."""
    resp = client.request("PROPFIND", "", headers={"Depth": "1"})
    if resp.status_code >= 400:
        return []
    alle = re.findall(r"([A-Za-z0-9\-_.]+\.vcf)", resp.text)
    return [name for name in alle if not _EIGENES_MUSTER.match(name)]


def _projekt_mitgliedschaften(conn, client) -> dict:
    """Liefert Apple-UID (fremder Kontakt) -> Liste von Rubrica-projekt_id, indem
    jede eigene projekt-N.vcf auf X-ADDRESSBOOKSERVER-MEMBER-Eintraege gescannt
    wird, die auf eine (noch) fremde UID zeigen (Rubricas eigene Mitglieder
    stehen dort als urn:uuid:kontakt-N, fremde Kontakte behalten ihre Apple-UID)."""
    projekt_ids = [row["id"] for row in conn.execute("SELECT id FROM projekte")]
    mitgliedschaften: dict = {}
    for projekt_id in projekt_ids:
        resp = client.get(f"projekt-{projekt_id}.vcf")
        if resp.status_code != 200:
            continue
        for uid in re.findall(r"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:([^\r\n]+)", resp.text):
            if uid.startswith("kontakt-"):
                continue  # Rubricas eigene Mitgliedschaft, hier nicht relevant
            mitgliedschaften.setdefault(uid, []).append(projekt_id)
    return mitgliedschaften


def _ordner_rohdaten(text: str, vcf_name: str) -> dict:
    """Baut die rohdaten fuer einen Ordner-Vorschlag aus einer fremden
    Gruppen-vCard - bewusst per Regex statt vobject-Parser (gleiches, bereits
    etablierte Muster wie bei _projekt_mitgliedschaften), da nur drei einfache
    Felder interessieren."""
    uid_match = re.search(r"^UID:(.+)$", text, re.MULTILINE)
    fn_match = re.search(r"^FN:(.+)$", text, re.MULTILINE)
    mitglieder_uids = [
        uid for uid in re.findall(r"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:([^\r\n]+)", text)
        if not uid.startswith("kontakt-")
    ]
    return {
        "typ": "ordner",
        "name": (fn_match.group(1).strip() if fn_match else vcf_name),
        "apple_gruppe_uid": (uid_match.group(1).strip() if uid_match else None),
        "mitglieder_uids": mitglieder_uids,
        "kontakte_app_vcf_name": vcf_name,
    }


def pruefe_kontakte_app_neuzugaenge(conn) -> dict:
    """Scannt Radicale nach fremden vCards, legt fuer jede neue (noch nicht als
    Vorschlag erfasste) einen offenen Vorschlag mit quelle='kontakte_app' an -
    fuer Kontakte wie fuer Gruppen-Neuanlagen (siehe Modul-Docstring). Wirft bei
    Verbindungsfehlern die zugrundeliegende Exception weiter (siehe
    pruefe_und_beschreibe fuer die fehlertolerante Anzeige-Variante)."""
    client = radicale._client()
    if client is None:
        return {"aktiv": False, "geprueft": 0, "neu": 0, "fehler": 0}

    geprueft = neu = fehler = 0
    try:
        namen = [n for n in _fremde_vcf_namen(client)
                 if not queries.vorschlag_existiert_fuer_message_id(conn, f"kontakte-app:{n}")]
        mitgliedschaften = _projekt_mitgliedschaften(conn, client) if namen else {}

        for name in namen:
            geprueft += 1
            message_id = f"kontakte-app:{name}"
            try:
                resp = client.get(name)
                if resp.status_code != 200:
                    fehler += 1
                    continue
                if _GRUPPEN_MUSTER.search(resp.text):
                    rohdaten = _ordner_rohdaten(resp.text, name)
                    queries.create_vorschlag(conn, rohdaten, quelle="kontakte_app", message_id=message_id)
                    neu += 1
                    continue
                for kontakt in parse_vcf(resp.text):
                    kontakt.pop("gruppen", None)
                    kontakt.pop("gruppen_uids", None)
                    apple_uid = kontakt.get("apple_uid")
                    kontakt["erkannte_ordner_ids"] = mitgliedschaften.get(apple_uid, []) if apple_uid else []
                    kontakt["kontakte_app_vcf_name"] = name
                    match_id = finde_match(conn, kontakt)
                    queries.create_vorschlag(conn, kontakt, kontakt_id=match_id,
                                              quelle="kontakte_app", message_id=message_id)
                    neu += 1
            except Exception:
                fehler += 1
    finally:
        client.close()

    return {"aktiv": True, "geprueft": geprueft, "neu": neu, "fehler": fehler}


def _eigene_mitglieder_auf_server(client, projekt_id: int) -> "set[int] | None":
    """Liest die kontakt_id der Mitglieder aus der Gruppen-vCard auf Radicale.
    None, wenn die vCard nicht (mehr) existiert oder nicht lesbar ist - dann darf
    kein Abgleich stattfinden, sonst gaelte eine fehlende Datei als "alle
    Mitglieder entfernt"."""
    resp = client.get(f"projekt-{projekt_id}.vcf")
    if resp.status_code != 200:
        return None
    ids = set()
    for uid in re.findall(r"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:kontakt-(\d+)", resp.text):
        ids.add(int(uid))
    return ids


def pruefe_ordner_mitgliedschaften(conn, client=None) -> dict:
    """Uebernimmt Ordner-Zuordnungen, die direkt in Kontakte.app geaendert wurden -
    also einen bestehenden Kontakt per Drag&Drop in eine Gruppe geschoben oder
    daraus entfernt. Ohne das bliebe eine solche Aenderung nicht nur unbemerkt,
    sondern wuerde beim naechsten push_projekt() lautlos zurueckgesetzt, weil
    dieses die Mitgliederliste komplett aus kontakte_projekte neu aufbaut.

    Dreiwege-Abgleich pro Ordner:
      S = Schnappschuss (was Rubrica zuletzt selbst gepusht hat)
      R = Mitglieder laut Gruppen-vCard auf Radicale (jetzt)
      D = Mitglieder laut Datenbank (jetzt)
    Alles, worin R von S abweicht, kann nur von einem Mac-Client stammen:
    R - S = dort hinzugefuegt, S - R = dort entfernt. Beides wird auf D
    angewandt, wobei Rubricas eigene Aenderungen seit dem Push (D gegen S)
    erhalten bleiben:  soll = (D | hinzugefuegt) - entfernt.
    Bei einem Konflikt (Rubrica entfernt, Client fuegt hinzu) gewinnt bewusst der
    Client - die Zuordnung wieder zu entfernen ist harmloser als sie zu verlieren.

    Ordner ohne Schnappschuss (nie gepusht, Z-Ordner, Altbestand vor Einfuehrung
    der Spalte) werden uebersprungen: fuer sie gibt es keinen verlaesslichen
    Bezugspunkt, jede Differenz waere Spekulation.

    `client`: optionale, bereits offene Verbindung (siehe sync/radicale.py::sync_alle) -
    der Vollabgleich soll fuer den gesamten Lauf EINE Verbindung nutzen, statt hier
    eine zweite aufzubauen."""
    eigener = client is None
    if eigener:
        client = radicale._client()
    if client is None:
        return {"aktiv": False, "geprueft": 0, "hinzugefuegt": 0, "entfernt": 0, "fehler": 0}

    geprueft = hinzugefuegt_gesamt = entfernt_gesamt = fehler = 0
    geaenderte_projekte: list[int] = []
    try:
        projekte = [dict(r) for r in conn.execute("SELECT id, name FROM projekte")]
        for projekt in projekte:
            projekt_id = projekt["id"]
            if radicale._ist_z_ordner(projekt["name"]):
                continue  # nie auf Radicale, siehe sync/radicale.py::push_projekt
            schnappschuss = queries.hole_gepushte_mitglieder(conn, projekt_id)
            if schnappschuss is None:
                continue
            try:
                server = _eigene_mitglieder_auf_server(client, projekt_id)
            except Exception:
                fehler += 1
                continue
            if server is None:
                continue

            geprueft += 1
            hinzugefuegt = server - schnappschuss
            entfernt = schnappschuss - server
            if not hinzugefuegt and not entfernt:
                continue

            # Nur Kontakte uebernehmen, die es in Rubrica wirklich (noch) gibt -
            # eine vCard kann auf einen zwischenzeitlich geloeschten Kontakt zeigen.
            if hinzugefuegt:
                vorhanden = {
                    r["id"] for r in conn.execute(
                        "SELECT id FROM kontakte WHERE id IN (%s)"
                        % ",".join("?" * len(hinzugefuegt)),
                        tuple(sorted(hinzugefuegt)),
                    )
                }
                hinzugefuegt &= vorhanden

            aktuell = {
                r["kontakt_id"] for r in conn.execute(
                    "SELECT kontakt_id FROM kontakte_projekte WHERE projekt_id = ?", (projekt_id,)
                )
            }
            soll = (aktuell | hinzugefuegt) - entfernt
            if soll == aktuell:
                continue

            queries.setze_kontakt_projekt_zuordnungen(conn, projekt_id, soll)
            hinzugefuegt_gesamt += len(soll - aktuell)
            entfernt_gesamt += len(aktuell - soll)
            geaenderte_projekte.append(projekt_id)

        # Erst nach dem Anwenden neu pushen: das schreibt den zusammengefuehrten
        # Stand zurueck und aktualisiert zugleich den Schnappschuss, damit dieselbe
        # Differenz beim naechsten Lauf nicht erneut angewandt wird.
        for projekt_id in geaenderte_projekte:
            radicale.push_projekt(conn, projekt_id, client=client)
    finally:
        if eigener:
            client.close()

    return {"aktiv": True, "geprueft": geprueft, "hinzugefuegt": hinzugefuegt_gesamt,
            "entfernt": entfernt_gesamt, "fehler": fehler}


def bestaetige_ordner_vorschlag(conn, vorschlag: dict) -> int:
    """Uebernimmt einen Ordner-Vorschlag (rohdaten.typ == "ordner"): legt den
    Ordner an bzw. findet ihn ueber die Apple-Gruppen-UID wieder
    (queries.get_or_create_projekt_von_apple_gruppe) und verknuepft jedes
    Mitglied, das bereits als Rubrica-Kontakt bekannt ist (Abgleich ueber dessen
    Apple-UID, erst JETZT beim Bestaetigen aufgeloest statt schon bei der
    Erkennung - siehe Modul-Docstring). Gibt die projekt_id zurueck."""
    daten = vorschlag["rohdaten"]
    projekt_id = queries.get_or_create_projekt_von_apple_gruppe(
        conn, daten.get("apple_gruppe_uid"), daten["name"]
    )
    for apple_uid in daten.get("mitglieder_uids", []):
        kontakt_id = queries.kontakt_id_von_apple_uid(conn, apple_uid)
        if kontakt_id:
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO kontakte_projekte (kontakt_id, projekt_id) VALUES (?, ?)",
                    (kontakt_id, projekt_id),
                )
    return projekt_id


def loesche_fremde_vcard(name: str) -> bool:
    """Entfernt eine urspruenglich fremde vCard (Ressourcenname aus rohdaten.
    kontakte_app_vcf_name) aus Radicale, nachdem der zugehoerige Vorschlag im
    Buero bestaetigt und unter Rubricas eigener UID (kontakt-N.vcf bzw.
    projekt-N.vcf) gepusht wurde (siehe web/vorschlaege.py) - verhindert eine
    doppelte Karte in Kontakte.app. Wie radicale._delete gilt ein 404 (bereits
    geloescht, z.B. weil ein Nutzer die vCard zwischenzeitlich selbst entfernt
    hat) bereits als Erfolg."""
    client = radicale._client()
    if client is None:
        return False
    try:
        resp = client.delete(name)
        return resp.status_code in (204, 404)
    except Exception:
        return False
    finally:
        client.close()


def pruefe_und_beschreibe(conn) -> str:
    """Fuehrt pruefe_kontakte_app_neuzugaenge() aus und baut daraus einen fertigen
    Anzeigetext - gemeinsam genutzt von web/vorschlaege.py (kombiniert mit
    mail_intake.pruefe_und_beschreibe zu einer gemeinsamen Meldung)."""
    try:
        ergebnis = pruefe_kontakte_app_neuzugaenge(conn)
        if not ergebnis["aktiv"]:
            return "Kein Radicale-Server konfiguriert."
        text = (f"{ergebnis['geprueft']} neue Kontakte.app-Einträge geprüft, "
                f"{ergebnis['neu']} neue Vorschläge angelegt.")
        if ergebnis["fehler"]:
            text += f" {ergebnis['fehler']} übersprungen (Fehler)."
    except Exception as exc:
        return f"Prüfung fehlgeschlagen: {type(exc).__name__}: {exc}"

    # Ordner-Zuordnungen werden direkt uebernommen (kein Vorschlag): eine
    # verschobene Mitgliedschaft aendert keine Kontaktdaten, sie ordnet nur zu.
    try:
        ordner = pruefe_ordner_mitgliedschaften(conn)
        if ordner["hinzugefuegt"] or ordner["entfernt"]:
            text += (f" Ordner-Zuordnungen aus Kontakte.app übernommen: "
                     f"{ordner['hinzugefuegt']} hinzugefügt, {ordner['entfernt']} entfernt.")
    except Exception as exc:
        text += f" Ordner-Abgleich fehlgeschlagen: {type(exc).__name__}: {exc}"
    return text
