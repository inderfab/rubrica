"""Erkennt Kontakte, die direkt in Kontakte.app (auf irgendeinem ueber CardDAV
verbundenen Mac) angelegt wurden, statt in Rubrica selbst - Radicales
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
(siehe web/vorschlaege.py) - nie automatisch uebernommen.

Dies ist die einzige bewusste Ausnahme von "Radicale wird nie gelesen, nur
beschrieben" (siehe sync/radicale.py-Modul-Docstring): dieses Modul liest
gezielt (PROPFIND + GET), schreibt aber nichts aus eigenem Antrieb - das
Loeschen der fremden vCard erfolgt erst nach expliziter Bestaetigung im Buero
(siehe web/vorschlaege.py), damit dort ein sauberer Kontakt (kontakt-N.vcf)
ohne Dublette entsteht.

Ordner-Erkennung ("wenn moeglich", Nutzer-Vorgabe): eine fremde Gruppen-
Neuanlage (wie "Neue Liste") wird NICHT als neuer Ordner uebernommen - nur eine
Mitgliedschaft in einem in Rubrica bereits bestehenden Ordner (projekt-N.vcf)
wird erkannt, durch Scannen von dessen X-ADDRESSBOOKSERVER-MEMBER-Zeilen nach
der Apple-UID des fremden Kontakts. Race bewusst in Kauf genommen: pusht
Rubrica einen Ordner (push_projekt) neu, BEVOR dieser Scan laeuft, baut das
die Mitgliederliste komplett aus der eigenen kontakte_projekte-Tabelle neu auf
und ueberschreibt damit eine gerade erst in Kontakte.app hinzugefuegte
Mitgliedschaft, ohne dass dieses Modul das noch sehen koennte.
"""
from __future__ import annotations

import re

from db import queries
from importer.vcard import finde_match, parse_vcf
from sync import radicale

_EIGENES_MUSTER = re.compile(r"^(kontakt|projekt)-\d+\.vcf$")


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


def pruefe_kontakte_app_neuzugaenge(conn) -> dict:
    """Scannt Radicale nach fremden vCards, legt fuer jede neue (noch nicht als
    Vorschlag erfasste) einen offenen Vorschlag mit quelle='kontakte_app' an.
    Wirft bei Verbindungsfehlern die zugrundeliegende Exception weiter (siehe
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
                # parse_vcf ignoriert fremde Gruppen-Definitionen (z.B. "Neue Liste")
                # automatisch (liefert dafuer eine leere Liste statt eines Kontakts).
                for kontakt in parse_vcf(resp.text):
                    kontakt.pop("gruppen", None)
                    gruppen_uids = kontakt.pop("gruppen_uids", None)
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


def loesche_fremde_vcard(name: str) -> bool:
    """Entfernt eine urspruenglich fremde vCard (Ressourcenname aus rohdaten.
    kontakte_app_vcf_name) aus Radicale, nachdem der zugehoerige Vorschlag im
    Buero bestaetigt und unter Rubricas eigener UID (kontakt-N.vcf) gepusht
    wurde (siehe web/vorschlaege.py) - verhindert eine doppelte Kontaktkarte
    in Kontakte.app. Wie radicale._delete gilt ein 404 (bereits geloescht,
    z.B. weil ein Nutzer die vCard zwischenzeitlich selbst entfernt hat)
    bereits als Erfolg."""
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
                f"{ergebnis['neu']} neue Kontaktvorschläge angelegt.")
        if ergebnis["fehler"]:
            text += f" {ergebnis['fehler']} übersprungen (Fehler)."
        return text
    except Exception as exc:
        return f"Prüfung fehlgeschlagen: {type(exc).__name__}: {exc}"
