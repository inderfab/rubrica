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

import hashlib
import re

from db import queries
from importer.vcard import finde_match, parse_vcf
from sync import radicale

_EIGENES_MUSTER = re.compile(r"^(kontakt|projekt)-\d+\.vcf$")

# message_id-Praefixe: zugleich Dublettenschutz und - bei den Loeschungen - Schluessel
# fuer die Push-Sperre (siehe queries.hat_offenen_loeschvorschlag).
LOESCHUNG_KONTAKT_PRAEFIX = "kontakte-app-loeschung:"
LOESCHUNG_ORDNER_PRAEFIX = "kontakte-app-ordner-loeschung:"
_GRUPPEN_MUSTER = re.compile(r"X-ADDRESSBOOKSERVER-KIND:\s*group", re.IGNORECASE)


def konfiguriert() -> bool:
    return bool(radicale.settings.get("radicale.base_url", ""))


def _fremde_vcf_namen(client) -> "list[str] | None":
    """Alle .vcf-Ressourcennamen im Adressbuch (PROPFIND, Tiefe 1), gefiltert auf
    alles, was NICHT Rubricas eigenem Namensmuster entspricht.

    None bedeutet "nicht abfragbar" und ist bewusst von der leeren Liste
    unterschieden: die leere Liste heisst "es gibt keine fremden Karten mehr" und
    zieht verwaiste Vorschlaege zurueck - bei einem Verbindungsfehler waere genau
    das falsch."""
    resp = client.request("PROPFIND", "", headers={"Depth": "1"})
    if resp.status_code >= 400:
        return None
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
    alle_uids = re.findall(r"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:([^\r\n]+)", text)
    # Zwei Sorten Mitglieder, beide relevant:
    # - fremde Apple-UIDs: in Kontakte.app neu angelegte Kontakte, die selbst noch
    #   als Vorschlag offen sind (werden erst beim Bestaetigen aufgeloest);
    # - kontakt-N: BESTEHENDE Rubrica-Kontakte, die in den neuen Ordner gezogen
    #   wurden. Diese wurden frueher herausgefiltert, weil die Logik nur auf fremde
    #   Neuanlagen ausgelegt war - dadurch entstand der Ordner beim Bestaetigen leer
    #   und die Zuordnung war weg (Nutzer-Meldung beim ersten Praxistest).
    return {
        "typ": "ordner",
        "name": (fn_match.group(1).strip() if fn_match else vcf_name),
        "apple_gruppe_uid": (uid_match.group(1).strip() if uid_match else None),
        "mitglieder_uids": [u for u in alle_uids if not u.startswith("kontakt-")],
        "mitglieder_kontakt_ids": [int(m.group(1)) for m in
                                    (re.match(r"^kontakt-(\d+)$", u) for u in alle_uids) if m],
        "kontakte_app_vcf_name": vcf_name,
    }


def _ohne_inhalt(kontakt: dict) -> bool:
    """Traegt die Karte ueberhaupt etwas, das man vorschlagen koennte?

    Kontakte.app legt eine Karte bereits beim Klick auf "+" an und schiebt sie
    sofort auf den Server - zu diesem Zeitpunkt ist sie noch komplett leer, der
    Name wird erst danach getippt. Ohne diese Pruefung entstand daraus ein
    Vorschlag ohne ein einziges Feld (Nutzer-Meldung: "sie erscheinen aber sie
    sind leer"). Uebersprungen wird er nur; sobald die Karte gefuellt ist, greift
    beim naechsten Durchlauf der normale Weg."""
    if any(str(kontakt.get(feld) or "").strip() for feld in ("vorname", "nachname", "firma")):
        return False
    return not any(kontakt.get(feld) for feld in ("telefonnummern", "emails", "adressen", "urls"))


def pruefe_kontakte_app_neuzugaenge(conn) -> dict:
    """Scannt Radicale nach fremden vCards, legt fuer jede neue (noch nicht als
    Vorschlag erfasste) einen offenen Vorschlag mit quelle='kontakte_app' an -
    fuer Kontakte wie fuer Gruppen-Neuanlagen (siehe Modul-Docstring). Wirft bei
    Verbindungsfehlern die zugrundeliegende Exception weiter (siehe
    pruefe_und_beschreibe fuer die fehlertolerante Anzeige-Variante)."""
    client = radicale._client()
    if client is None:
        return {"aktiv": False, "geprueft": 0, "neu": 0, "aktualisiert": 0, "fehler": 0}

    geprueft = neu = fehler = aktualisiert = zurueckgezogen = 0
    try:
        alle_namen = _fremde_vcf_namen(client)
        if alle_namen is None:
            return {"aktiv": True, "geprueft": 0, "neu": 0, "aktualisiert": 0,
                    "zurueckgezogen": 0, "fehler": 1}
        namen, nachzuziehen = [], []
        for n in alle_namen:
            offener = queries.offener_vorschlag_fuer_message_id(conn, f"kontakte-app:{n}")
            if offener is not None:
                # Wurde die vCard nach der Erfassung noch korrigiert (Tippfehler im
                # Namen o.ae.), muss der Vorschlag mitgezogen werden - sonst legt das
                # Uebernehmen die alte Fassung an und die Korrektur geht mit der
                # geloeschten fremden vCard verloren.
                nachzuziehen.append((n, offener))
            elif not queries.vorschlag_existiert_fuer_message_id(conn, f"kontakte-app:{n}"):
                namen.append(n)
        mitgliedschaften = _projekt_mitgliedschaften(conn, client) if (namen or nachzuziehen) else {}

        for name, offener in nachzuziehen:
            try:
                resp = client.get(name)
                if resp.status_code != 200 or _GRUPPEN_MUSTER.search(resp.text):
                    continue
                for kontakt in parse_vcf(resp.text):
                    kontakt.pop("gruppen", None)
                    kontakt.pop("gruppen_uids", None)
                    apple_uid = kontakt.get("apple_uid")
                    kontakt["erkannte_ordner_ids"] = mitgliedschaften.get(apple_uid, []) if apple_uid else []
                    kontakt["kontakte_app_vcf_name"] = name
                    if kontakt != offener["rohdaten"]:
                        queries.update_vorschlag_rohdaten(conn, offener["id"], kontakt)
                        aktualisiert += 1
                    break
            except Exception:
                fehler += 1

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
                    if _ohne_inhalt(kontakt):
                        continue
                    match_id = finde_match(conn, kontakt)
                    queries.create_vorschlag(conn, kontakt, kontakt_id=match_id,
                                              quelle="kontakte_app", message_id=message_id)
                    neu += 1
            except Exception:
                fehler += 1
        zurueckgezogen = _ziehe_verwaiste_vorschlaege_zurueck(conn, alle_namen)
    finally:
        client.close()

    return {"aktiv": True, "geprueft": geprueft, "neu": neu, "aktualisiert": aktualisiert,
            "zurueckgezogen": zurueckgezogen, "fehler": fehler}


def _ziehe_verwaiste_vorschlaege_zurueck(conn, vorhandene_namen: list) -> int:
    """Schliesst offene Kontakte.app-Vorschlaege, zu denen es nichts mehr zu
    entscheiden gibt:

    - Die zugehoerige Karte liegt nicht mehr auf dem Server. Sie wurde in
      Kontakte.app wieder geloescht (oder unter neuer UID ersetzt) - der Vorschlag
      zeigt dann auf etwas, das es nicht mehr gibt, und liesse sich nicht einmal
      mehr sinnvoll uebernehmen.
    - Der Vorschlag ist inhaltlich leer geblieben. Das passiert bei einer Karte,
      die Kontakte.app beim Klick auf "+" anlegt und die nie gefuellt wurde."""
    vorhanden = set(vorhandene_namen)
    zurueckgezogen = 0
    for vorschlag in queries.list_vorschlaege(conn, status="offen", quelle="kontakte_app"):
        if not (vorschlag["message_id"] or "").startswith("kontakte-app:"):
            continue  # Aenderungs-/Loeschvorschlaege haben eigene Praefixe
        rohdaten = vorschlag["rohdaten"] or {}
        if rohdaten.get("typ") == "ordner":
            continue
        name = rohdaten.get("kontakte_app_vcf_name")
        if name in vorhanden and not _ohne_inhalt(rohdaten):
            continue
        queries.set_vorschlag_status(conn, vorschlag["id"], "abgelehnt")
        zurueckgezogen += 1
    return zurueckgezogen


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
        return {"aktiv": False, "geprueft": 0, "hinzugefuegt": 0, "entfernt": 0, "umbenannt": 0, "fehler": 0}

    geprueft = hinzugefuegt_gesamt = entfernt_gesamt = fehler = umbenannt = 0
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
            roh = radicale.gruppen_vcard_auf_server(projekt_id, client=client)
            if roh is None:
                # Es gab einen bestaetigten Push, jetzt ist die Gruppe weg - in
                # Kontakte.app geloescht. Als Vorschlag vorlegen (siehe
                # pruefe_kontakt_aenderungen fuer dieselbe Ueberlegung bei Kontakten).
                message_id = f"{LOESCHUNG_ORDNER_PRAEFIX}{projekt_id}"
                if not queries.vorschlag_existiert_fuer_message_id(conn, message_id):
                    queries.create_vorschlag(conn, {
                        "typ": "loeschung_ordner", "name": projekt["name"],
                        "projekt_id": projekt_id,
                    }, quelle="kontakte_app", message_id=message_id)
                continue

            server, server_name = roh
            # Umbenennung wirkt direkt - sie aendert keine Kontaktdaten, nur eine
            # Bezeichnung (dieselbe Ueberlegung wie beim Verschieben in Ordner).
            if server_name and server_name != projekt["name"]:
                try:
                    queries.rename_projekt(conn, projekt_id, server_name)
                    projekt["name"] = server_name
                    umbenannt += 1
                except Exception:
                    # Namen sind eindeutig: kollidiert der neue mit einem bestehenden
                    # Ordner, bleibt es beim alten statt den Push scheitern zu lassen.
                    fehler += 1

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
            "entfernt": entfernt_gesamt, "umbenannt": umbenannt, "fehler": fehler}


# Felder, die aus einer vCard verlaesslich zurueckgelesen werden koennen. Bewusst
# NICHT enthalten: "kategorie" (die Funktion). Rubrica schreibt sie zwar als
# CATEGORIES in die vCard, importer/vcard.py._parse_kontakt liefert dafuer aber
# immer "" zurueck - wuerde man sie mitvergleichen, sae­he jede Aenderung so aus, als
# haette jemand die Funktion geleert, und das Uebernehmen wuerde ein Pflichtfeld
# loeschen. Da der Wert in Schnappschuss und Serverstand gleichermassen "" ist,
# faellt er beim Diff ohnehin nie auf.
_VERGLEICHSFELDER = ("vorname", "nachname", "firma", "rolle", "notizen",
                     "telefonnummern", "emails", "adressen", "urls")

_FELD_BESCHRIFTUNG = {
    "vorname": "Vorname", "nachname": "Nachname", "firma": "Firma", "rolle": "Rolle",
    "notizen": "Notizen", "telefonnummern": "Telefon", "emails": "E-Mail",
    "adressen": "Adresse", "urls": "Web",
}


def _erste_vcard(text: str):
    """Parst eine vCard zu einem Kontakt-Dict, oder None wenn sie unbrauchbar ist."""
    try:
        kontakte = parse_vcf(text)
    except Exception:
        return None
    return kontakte[0] if kontakte else None


def _lesbar(feld: str, wert) -> str:
    """Vergleichswerte fuer die Anzeige aufbereiten - aus Listen von Dicts wird ein
    lesbarer, stabil sortierter Text."""
    if isinstance(wert, list):
        teile = []
        for eintrag in wert:
            if not isinstance(eintrag, dict):
                teile.append(str(eintrag))
                continue
            if "nummer" in eintrag:
                text = eintrag["nummer"]
            elif "email" in eintrag:
                text = eintrag["email"]
            elif "url" in eintrag:
                text = eintrag["url"]
            else:  # Adresse
                text = " ".join(str(eintrag.get(k, "")) for k in
                                ("strasse", "plz", "ort", "land")).strip()
            # Kategorie mitzeigen: sonst steht bei einer reinen Umkategorisierung
            # (z.B. Direkt -> Privat) links und rechts derselbe Wert und die
            # Gegenueberstellung wirkt wie ein Fehler.
            typ = (eintrag.get("typ") or "").strip()
            teile.append(f"{typ}: {text}" if typ and text else text)
        return ", ".join(t for t in teile if t)
    return str(wert or "")


def _vergleichswert(eintrag) -> str:
    """Normalisiert einen Listeneintrag fuer den VERGLEICH (nicht fuer die Anzeige).

    Kontakte.app schreibt Werte in eigener Schreibweise zurueck - eine Telefonnummer
    kommt mit anderen Leerzeichen/Bindestrichen wieder, eine Adresse in anderer
    Gross-/Kleinschreibung. Ohne Normalisierung meldet Rubrica dann eine Aenderung,
    obwohl inhaltlich nichts anders ist (Nutzer-Meldung: "zeigt die telefonnummer als
    geaendert an obwohl ich daran nicht geaendert habe"). Die Kategorie bleibt Teil
    des Vergleichs, damit eine echte Umstellung (Direkt -> Privat) weiterhin auffaellt."""
    if not isinstance(eintrag, dict):
        return str(eintrag).strip().lower()
    typ = (eintrag.get("typ") or "").strip().lower()
    if "nummer" in eintrag:
        return f"tel|{typ}|" + re.sub(r"\D", "", eintrag["nummer"] or "")
    if "email" in eintrag:
        return f"mail|{typ}|" + (eintrag["email"] or "").strip().lower()
    if "url" in eintrag:
        return f"url|{typ}|" + (eintrag["url"] or "").strip().lower().rstrip("/")
    felder = ("strasse", "plz", "ort", "region", "land")
    return f"adr|{typ}|" + "|".join(
        " ".join(str(eintrag.get(f, "") or "").split()).lower() for f in felder
    )


def _entspricht_der_datenbank(bestehend: dict, feld: str, wert) -> bool:
    """Steht der Serverwert bereits so in Rubrica?

    Dann ist es keine Aenderung aus Kontakte.app, sondern Rubricas eigener Stand -
    und ein Vorschlag "uebernimm, was ohnehin schon dasteht" waere sinnlos.
    Konkreter Anlass: die Umstellung der Telefon-Kategorien hat den Datenbankstand
    veraendert. Der Schnappschuss stammte noch von davor, der Server hatte den
    neuen Stand bereits - daraus wurden reihenweise Vorschlaege fuer Nummern, die
    niemand angefasst hatte (Nutzer-Meldung)."""
    if bestehend is None or feld not in bestehend:
        return False
    db_wert = bestehend[feld]
    if isinstance(wert, list) or isinstance(db_wert, list):
        return sorted(_vergleichswert(e) for e in (wert or [])) == \
               sorted(_vergleichswert(e) for e in (db_wert or []))
    return " ".join(str(wert or "").split()) == " ".join(str(db_wert or "").split())


def _feld_unterschiede(alt: dict, neu: dict) -> dict:
    """Vergleicht zwei geparste Kontakte und liefert nur die abweichenden Felder.

    Verglichen wird geparster Schnappschuss gegen geparsten Serverstand - nicht
    gegen den Datenbankstand. Dadurch bleiben Felder, die der vCard-Parser nicht
    zurueckliest, in beiden Seiten identisch und tauchen nie als "Aenderung" auf."""
    unterschiede = {}
    for feld in _VERGLEICHSFELDER:
        a, n = alt.get(feld), neu.get(feld)
        if isinstance(a, list) or isinstance(n, list):
            # Reihenfolge ist in vCards nicht bedeutungstragend, Schreibweise ebenso
            # wenig (siehe _vergleichswert).
            if sorted(_vergleichswert(e) for e in (a or [])) == \
               sorted(_vergleichswert(e) for e in (n or [])):
                continue
        elif " ".join((a or "").split()) == " ".join((n or "").split()):
            continue
        unterschiede[feld] = {
            "feld": _FELD_BESCHRIFTUNG.get(feld, feld),
            "alt": _lesbar(feld, a),
            "neu": _lesbar(feld, n),
            "wert": n,
        }
    return unterschiede


def pruefe_kontakt_aenderungen(conn, client=None) -> dict:
    """Erkennt Feldaenderungen, die jemand direkt in Kontakte.app an einem bereits
    bestehenden Rubrica-Kontakt vorgenommen hat (z.B. eine korrigierte
    Telefonnummer), und legt sie als Vorschlag an - uebernommen wird nichts
    automatisch. Begruendung (Nutzer-Vorgabe): eine Aenderung ist wie eine
    Neuanlage zu behandeln, weil sie auch versehentlich passiert sein kann; im
    Browser sieht man sie dann und kann sie uebernehmen oder verwerfen.

    Vergleichsstand ist die zuletzt von Rubrica selbst gepushte vCard
    (kontakte.zuletzt_gepushte_vcard). Kontakte ohne diesen Stand werden
    uebersprungen - ohne Referenzpunkt waere jede Abweichung Spekulation.

    Dublettenschutz laeuft ueber einen Inhalts-Hash: solange dieselbe Aenderung
    unbestaetigt auf dem Server steht, entsteht bei jedem Lauf derselbe
    message_id-Wert und damit kein zweiter Vorschlag. Eine spaetere, andere
    Aenderung am selben Kontakt erzeugt dagegen einen neuen."""
    eigener = client is None
    if eigener:
        client = radicale._client()
    if client is None:
        return {"aktiv": False, "geprueft": 0, "neu": 0, "fehler": 0}

    geprueft = neu = fehler = zurueckgezogen = 0
    try:
        for eintrag in queries.kontakte_mit_gepushter_vcard(conn):
            kontakt_id = eintrag["id"]
            try:
                resp = client.get(f"kontakt-{kontakt_id}.vcf")
            except Exception:
                fehler += 1
                continue
            if resp.status_code == 404:
                # Es gab einen bestaetigten Push, jetzt ist die vCard weg - jemand hat
                # den Kontakt in Kontakte.app geloescht. Als Vorschlag vorlegen statt
                # still zu ignorieren (sonst schriebe ihn der naechste Push wortlos
                # zurueck und die Loeschung waere wirkungslos).
                message_id = f"{LOESCHUNG_KONTAKT_PRAEFIX}{kontakt_id}"
                if queries.vorschlag_existiert_fuer_message_id(conn, message_id):
                    continue
                bestehend = queries.get_kontakt(conn, kontakt_id)
                if bestehend is None:
                    continue
                geprueft += 1
                queries.create_vorschlag(conn, {
                    "typ": "loeschung",
                    "vorname": bestehend["vorname"], "nachname": bestehend["nachname"],
                    "firma": bestehend["firma"],
                }, kontakt_id=kontakt_id, quelle="kontakte_app", message_id=message_id)
                neu += 1
                continue
            if resp.status_code != 200:
                continue  # nicht lesbar - kein Rueckschluss moeglich

            unterschiede = {}
            jetzt = None
            if resp.text.strip() != (eintrag["vcard"] or "").strip():
                geprueft += 1
                alt = _erste_vcard(eintrag["vcard"] or "")
                jetzt = _erste_vcard(resp.text)
                if alt is None or jetzt is None:
                    fehler += 1
                    continue
                # Kein Unterschied heisst: nur Formatierung/Reihenfolge weichen ab.
                unterschiede = _feld_unterschiede(alt, jetzt)
                bestehend = queries.get_kontakt(conn, kontakt_id) if unterschiede else None
                unterschiede = {
                    feld: d for feld, d in unterschiede.items()
                    if not _entspricht_der_datenbank(bestehend, feld, d["wert"])
                }

            message_id = None
            if unterschiede:
                rumpf = "|".join(f"{f}={d['neu']}" for f, d in sorted(unterschiede.items()))
                message_id = f"kontakte-app-aenderung:{kontakt_id}:{hashlib.sha1(rumpf.encode()).hexdigest()[:12]}"

            # Offene Vorschlaege zurueckziehen, die den aktuellen Stand nicht mehr
            # abbilden: der Unterschied ist verschwunden (jemand hat ihn im Browser
            # nachgezogen, oder er war nie einer - siehe die falschen
            # Umkategorisierungen durch den kaputten vCard-Rueckweg), oder es steht
            # inzwischen eine ANDERE Aenderung an. Ohne das blieben sie fuer immer
            # in der Liste stehen und muessten von Hand einzeln weggeklickt werden.
            for offener in queries.offene_aenderungs_vorschlaege(conn, kontakt_id):
                if offener["message_id"] != message_id:
                    queries.set_vorschlag_status(conn, offener["id"], "abgelehnt")
                    zurueckgezogen += 1

            if message_id is None:
                continue
            if queries.vorschlag_existiert_fuer_message_id(conn, message_id):
                continue

            queries.create_vorschlag(conn, {
                "typ": "aenderung",
                "vorname": jetzt.get("vorname", ""),
                "nachname": jetzt.get("nachname", ""),
                "firma": jetzt.get("firma", ""),
                "unterschiede": list(unterschiede.values()),
                "geaenderte_felder": {f: d["wert"] for f, d in unterschiede.items()},
            }, kontakt_id=kontakt_id, quelle="kontakte_app", message_id=message_id)
            neu += 1
    finally:
        if eigener:
            client.close()

    return {"aktiv": True, "geprueft": geprueft, "neu": neu,
            "zurueckgezogen": zurueckgezogen, "fehler": fehler}


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
    zu_verknuepfen = []
    for apple_uid in daten.get("mitglieder_uids", []):
        kontakt_id = queries.kontakt_id_von_apple_uid(conn, apple_uid)
        if kontakt_id:
            zu_verknuepfen.append(kontakt_id)
    # Bestehende Rubrica-Kontakte, die in Kontakte.app in den neuen Ordner gezogen
    # wurden - der haeufigste Fall ueberhaupt und frueher stillschweigend verloren.
    for kontakt_id in daten.get("mitglieder_kontakt_ids", []):
        if queries.get_kontakt(conn, kontakt_id) is not None:
            zu_verknuepfen.append(kontakt_id)

    for kontakt_id in zu_verknuepfen:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO kontakte_projekte (kontakt_id, projekt_id) VALUES (?, ?)",
                (kontakt_id, projekt_id),
            )
    return projekt_id


def bestaetige_aenderungs_vorschlag(conn, vorschlag: dict) -> int:
    """Uebernimmt eine in Kontakte.app vorgenommene Feldaenderung. Angewandt werden
    NUR die als abweichend erkannten Felder - der bestehende Kontakt wird nicht
    durch die geparste vCard ersetzt. Sonst gingen Felder verloren, die eine vCard
    nicht zurueckliefert, allen voran die Funktion (siehe _VERGLEICHSFELDER).
    Gibt die kontakt_id zurueck."""
    kontakt_id = vorschlag["kontakt_id"]
    bestehend = queries.get_kontakt(conn, kontakt_id)
    if bestehend is None:
        raise ValueError(f"Kontakt {kontakt_id} existiert nicht mehr")

    daten = dict(bestehend)
    daten.update(vorschlag["rohdaten"].get("geaenderte_felder", {}))
    queries.update_kontakt(conn, kontakt_id, daten)
    return kontakt_id


def verwerfe_aenderungs_vorschlag(conn, vorschlag: dict) -> int:
    """Verwirft eine Feldaenderung und stellt Rubricas Stand auf allen Geraeten
    wieder her. Der Push ist hier zwingend, nicht optional: ohne ihn bliebe die
    abgelehnte Aenderung auf dem Server stehen und waere weiterhin auf allen
    Geraeten sichtbar - abgelehnt waere sie dann nur in Rubricas Datenbank."""
    kontakt_id = vorschlag["kontakt_id"]
    radicale.push_kontakt(conn, kontakt_id)
    return kontakt_id


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
        if ergebnis.get("zurueckgezogen"):
            text += (f" {ergebnis['zurueckgezogen']} gegenstandslose Vorschläge "
                     f"zurückgezogen.")
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

    # Feldaenderungen dagegen NICHT automatisch - sie kommen als Vorschlag.
    try:
        aenderungen = pruefe_kontakt_aenderungen(conn)
        if aenderungen["neu"]:
            text += f" {aenderungen['neu']} geänderte Kontakte gefunden."
        if aenderungen.get("zurueckgezogen"):
            text += (f" {aenderungen['zurueckgezogen']} Änderungsvorschläge "
                     f"zurückgezogen (Unterschied besteht nicht mehr).")
    except Exception as exc:
        text += f" Änderungserkennung fehlgeschlagen: {type(exc).__name__}: {exc}"
    return text
