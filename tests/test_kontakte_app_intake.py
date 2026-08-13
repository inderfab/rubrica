import httpx

import kontakte_app_intake
from config import settings
from db import queries
from sync import radicale

_FREMDE_VCARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:ABC-123-FREMD\r\n"
    "FN:Max Mustermann\r\n"
    "N:Mustermann;Max;;;\r\n"
    "EMAIL;TYPE=INTERNET:max@example.com\r\n"
    "END:VCARD\r\n"
)

_FREMDE_GRUPPEN_VCARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:GRUPPE-1-FREMD\r\n"
    "FN:Neue Liste\r\n"
    "N:Neue Liste;;;;\r\n"
    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
    "END:VCARD\r\n"
)


def _propfind_xml(namen: list[str]) -> str:
    hrefs = "".join(f"<response><href>/rubrica/kontakte/{n}</href></response>" for n in namen)
    return f"<multistatus>{hrefs}</multistatus>"


def test_konfiguriert_spiegelt_base_url(monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": ""}})
    assert kontakte_app_intake.konfiguriert() is False
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": "https://127.0.0.1:8443"}})
    assert kontakte_app_intake.konfiguriert() is True


def test_ohne_radicale_konfiguration_meldet_inaktiv(tmp_db, monkeypatch):
    monkeypatch.setattr(radicale, "_client", lambda: None)
    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    assert ergebnis["aktiv"] is False and ergebnis["neu"] == 0


def test_erkennt_fremde_vcard_als_vorschlag(tmp_db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["kontakt-1.vcf", "ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert (ergebnis["aktiv"], ergebnis["geprueft"], ergebnis["neu"], ergebnis["fehler"]) == (True, 1, 1, 0)
    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert len(vorschlaege) == 1
    v = vorschlaege[0]
    assert v["rohdaten"]["vorname"] == "Max"
    assert v["rohdaten"]["nachname"] == "Mustermann"
    assert v["rohdaten"]["kontakte_app_vcf_name"] == "ABC-123-FREMD.vcf"
    assert v["message_id"] == "kontakte-app:ABC-123-FREMD.vcf"
    assert v["status"] == "offen"
    # Rubricas eigene kontakt-1.vcf darf nie als Vorschlag landen.
    assert not any(vv["rohdaten"].get("kontakte_app_vcf_name") == "kontakt-1.vcf" for vv in vorschlaege)


def test_erkennt_fremde_gruppe_als_ordner_vorschlag(tmp_db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["GRUPPE-1-FREMD.vcf"]))
        if request.url.path == "/a/GRUPPE-1-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_GRUPPEN_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis["neu"] == 1
    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert len(vorschlaege) == 1
    v = vorschlaege[0]
    assert v["rohdaten"]["typ"] == "ordner"
    assert v["rohdaten"]["name"] == "Neue Liste"
    assert v["rohdaten"]["apple_gruppe_uid"] == "GRUPPE-1-FREMD"
    assert v["rohdaten"]["kontakte_app_vcf_name"] == "GRUPPE-1-FREMD.vcf"
    assert v["message_id"] == "kontakte-app:GRUPPE-1-FREMD.vcf"


def test_bestaetige_ordner_vorschlag_legt_ordner_an_und_verknuepft_bekannte_mitglieder(tmp_db):
    bekannter_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster",
                                                     "apple_uid": "ANNA-UID"})
    vorschlag_id = queries.create_vorschlag(tmp_db, {
        "typ": "ordner", "name": "Neue Liste", "apple_gruppe_uid": "GRUPPE-1-FREMD",
        "mitglieder_uids": ["ANNA-UID", "UNBEKANNT-UID"], "kontakte_app_vcf_name": "GRUPPE-1-FREMD.vcf",
    }, quelle="kontakte_app")
    vorschlag = queries.get_vorschlag(tmp_db, vorschlag_id)

    projekt_id = kontakte_app_intake.bestaetige_ordner_vorschlag(tmp_db, vorschlag)

    ordner = queries.list_projekte(tmp_db)
    assert any(o["id"] == projekt_id and o["name"] == "Neue Liste" for o in ordner)
    kontakt = queries.get_kontakt(tmp_db, bekannter_id)
    assert [p["id"] for p in kontakt["projekte"]] == [projekt_id]


def test_erkennt_ordner_mitgliedschaft_aus_eigener_projekt_vcard(tmp_db, monkeypatch):
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle Muster")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        if request.url.path == f"/a/projekt-{projekt_id}.vcf":
            return httpx.Response(
                200,
                text=(
                    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:projekt-{0}\r\nFN:Baustelle Muster\r\n"
                    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
                    "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:ABC-123-FREMD\r\nEND:VCARD\r\n"
                ).format(projekt_id),
            )
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert len(vorschlaege) == 1
    assert vorschlaege[0]["rohdaten"]["erkannte_ordner_ids"] == [projekt_id]


def test_dedup_ueber_message_id_verhindert_erneuten_vorschlag(tmp_db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    erster_lauf = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    zweiter_lauf = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert erster_lauf["neu"] == 1
    assert zweiter_lauf["geprueft"] == 0
    assert zweiter_lauf["neu"] == 0
    assert len(queries.list_vorschlaege(tmp_db, quelle="kontakte_app")) == 1


def test_erkennt_moeglichen_duplikat_treffer_ueber_email(tmp_db, monkeypatch):
    bestehender_id = queries.create_kontakt(tmp_db, {
        "vorname": "Max", "nachname": "Mustermann",
        "emails": [{"typ": "Direkt", "email": "max@example.com"}],
    })

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert vorschlaege[0]["kontakt_id"] == bestehender_id


def test_pruefe_und_beschreibe_ohne_konfiguration(tmp_db, monkeypatch):
    monkeypatch.setattr(radicale, "_client", lambda: None)
    text = kontakte_app_intake.pruefe_und_beschreibe(tmp_db)
    assert "Kein Radicale-Server konfiguriert" in text


def test_pruefe_und_beschreibe_fasst_ergebnis_zusammen(tmp_db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    text = kontakte_app_intake.pruefe_und_beschreibe(tmp_db)
    assert "1 neue Kontakte.app-Einträge geprüft" in text
    assert "1 neue Vorschläge angelegt" in text


# ── Ordner-Mitgliedschaften: in Kontakte.app verschobene Kontakte ────────────
# Ohne diesen Abgleich bliebe ein dort per Drag&Drop verschobener Kontakt nicht nur
# unbemerkt, sondern wuerde beim naechsten push_projekt() lautlos zurueckgesetzt
# (push_projekt baut die Mitgliederliste komplett aus kontakte_projekte neu auf).

def _gruppen_vcard(projekt_id: int, kontakt_ids: list) -> str:
    zeilen = [
        "BEGIN:VCARD", "VERSION:3.0", f"UID:projekt-{projekt_id}",
        "FN:Testordner", "X-ADDRESSBOOKSERVER-KIND:group",
    ]
    zeilen += [f"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:kontakt-{k}" for k in kontakt_ids]
    zeilen.append("END:VCARD")
    return "\r\n".join(zeilen) + "\r\n"


def _mock_client(monkeypatch, handler):
    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))


def _mitglieder(conn, projekt_id):
    return {r["kontakt_id"] for r in conn.execute(
        "SELECT kontakt_id FROM kontakte_projekte WHERE projekt_id = ?", (projekt_id,))}


def test_in_kontakte_app_hinzugefuegte_zuordnung_wird_uebernommen(tmp_db, monkeypatch):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    # Rubrica hat zuletzt nur k1 gepusht; auf dem Server steht jetzt zusaetzlich k2.
    queries.setze_gepushte_mitglieder(tmp_db, projekt_id, [k1])

    def handler(request):
        if request.url.path == f"/a/projekt-{projekt_id}.vcf" and request.method == "GET":
            return httpx.Response(200, text=_gruppen_vcard(projekt_id, [k1, k2]))
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    ergebnis = kontakte_app_intake.pruefe_ordner_mitgliedschaften(tmp_db)

    assert ergebnis["hinzugefuegt"] == 1
    assert ergebnis["entfernt"] == 0
    assert _mitglieder(tmp_db, projekt_id) == {k1, k2}
    # Schnappschuss ist nach dem Ruecksch­reiben aktuell -> kein erneutes Anwenden.
    assert queries.hole_gepushte_mitglieder(tmp_db, projekt_id) == {k1, k2}


def test_in_kontakte_app_entfernte_zuordnung_wird_uebernommen(tmp_db, monkeypatch):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    queries.set_kontakt_projekte(tmp_db, k2, [projekt_id])
    queries.setze_gepushte_mitglieder(tmp_db, projekt_id, [k1, k2])

    def handler(request):
        if request.url.path == f"/a/projekt-{projekt_id}.vcf" and request.method == "GET":
            return httpx.Response(200, text=_gruppen_vcard(projekt_id, [k1]))
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    ergebnis = kontakte_app_intake.pruefe_ordner_mitgliedschaften(tmp_db)

    assert ergebnis["entfernt"] == 1
    assert _mitglieder(tmp_db, projekt_id) == {k1}


def test_gleichzeitige_rubrica_aenderung_bleibt_erhalten(tmp_db, monkeypatch):
    """Rubrica hat seit dem letzten Push k3 ergaenzt, in Kontakte.app wurde k2
    hinzugefuegt - beide Aenderungen muessen ueberleben."""
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel"})
    k3 = queries.create_kontakt(tmp_db, {"vorname": "Carla", "nachname": "Kunz"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    queries.set_kontakt_projekte(tmp_db, k3, [projekt_id])   # Rubrica-Aenderung
    queries.setze_gepushte_mitglieder(tmp_db, projekt_id, [k1])

    def handler(request):
        if request.url.path == f"/a/projekt-{projekt_id}.vcf" and request.method == "GET":
            return httpx.Response(200, text=_gruppen_vcard(projekt_id, [k1, k2]))
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    kontakte_app_intake.pruefe_ordner_mitgliedschaften(tmp_db)

    assert _mitglieder(tmp_db, projekt_id) == {k1, k2, k3}


def test_ohne_schnappschuss_wird_nichts_angetastet(tmp_db, monkeypatch):
    """Ordner aus einer Installation von vor dieser Spalte (oder nie gepusht):
    ohne Referenzpunkt waere jede Differenz Spekulation."""
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])

    def handler(request):
        if request.url.path == f"/a/projekt-{projekt_id}.vcf" and request.method == "GET":
            return httpx.Response(200, text=_gruppen_vcard(projekt_id, []))
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    ergebnis = kontakte_app_intake.pruefe_ordner_mitgliedschaften(tmp_db)

    assert ergebnis["geprueft"] == 0
    assert _mitglieder(tmp_db, projekt_id) == {k1}


def test_fehlende_vcard_gilt_nicht_als_alle_entfernt(tmp_db, monkeypatch):
    """Regression-Schutz: ein 404 (Push fehlgeschlagen, vCard noch nicht da) darf
    nicht als "alle Mitglieder in Kontakte.app entfernt" gedeutet werden."""
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    queries.setze_gepushte_mitglieder(tmp_db, projekt_id, [k1])

    _mock_client(monkeypatch, lambda request: httpx.Response(404))
    ergebnis = kontakte_app_intake.pruefe_ordner_mitgliedschaften(tmp_db)

    assert ergebnis["geprueft"] == 0
    assert _mitglieder(tmp_db, projekt_id) == {k1}


def test_z_ordner_werden_uebersprungen(tmp_db, monkeypatch):
    """Z-Ordner liegen bewusst nie auf Radicale (siehe radicale._ist_z_ordner)."""
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Z1_Archiv")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    queries.setze_gepushte_mitglieder(tmp_db, projekt_id, [k1])

    angefragt = []

    def handler(request):
        angefragt.append(request.url.path)
        return httpx.Response(404)

    _mock_client(monkeypatch, handler)
    kontakte_app_intake.pruefe_ordner_mitgliedschaften(tmp_db)

    assert angefragt == []
    assert _mitglieder(tmp_db, projekt_id) == {k1}


def test_unbekannter_kontakt_in_vcard_wird_ignoriert(tmp_db, monkeypatch):
    """Die vCard kann auf einen zwischenzeitlich geloeschten Kontakt zeigen."""
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    queries.setze_gepushte_mitglieder(tmp_db, projekt_id, [k1])

    def handler(request):
        if request.url.path == f"/a/projekt-{projekt_id}.vcf" and request.method == "GET":
            return httpx.Response(200, text=_gruppen_vcard(projekt_id, [k1, 99999]))
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    kontakte_app_intake.pruefe_ordner_mitgliedschaften(tmp_db)

    assert _mitglieder(tmp_db, projekt_id) == {k1}


def test_push_projekt_haelt_schnappschuss_fest(tmp_db, monkeypatch):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    assert queries.hole_gepushte_mitglieder(tmp_db, projekt_id) is None

    _mock_client(monkeypatch, lambda request: httpx.Response(201))
    radicale.push_projekt(tmp_db, projekt_id)

    assert queries.hole_gepushte_mitglieder(tmp_db, projekt_id) == {k1}


def test_fehlgeschlagener_push_setzt_keinen_schnappschuss(tmp_db, monkeypatch):
    """Sonst waere der Referenzpunkt falsch und der naechste Abgleich wuerde die
    Differenz faelschlich einem Mac-Client zuschreiben."""
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])

    _mock_client(monkeypatch, lambda request: httpx.Response(500))
    radicale.push_projekt(tmp_db, projekt_id)

    assert queries.hole_gepushte_mitglieder(tmp_db, projekt_id) is None


def test_gleichzeitige_aenderung_geht_nicht_verloren(tmp_db, monkeypatch):
    """Regression (Nutzer-Frage zu 20 verbundenen Geraeten): Kollege zieht in
    Kontakte.app B in einen Ordner, kurz darauf fuegt jemand im Browser C zum selben
    Ordner hinzu - BEVOR der Hintergrund-Scan lief. Vor dem Lesen-vor-Schreiben in
    push_projekt ueberschrieb dieser Push die Gruppen-vCard blind mit dem
    Datenbankstand, B war damit lautlos und unwiederbringlich weg."""
    A = queries.create_kontakt(tmp_db, {"vorname": "A", "nachname": "Alt"})
    B = queries.create_kontakt(tmp_db, {"vorname": "B", "nachname": "VomMac"})
    C = queries.create_kontakt(tmp_db, {"vorname": "C", "nachname": "VomBrowser"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, A, [projekt_id])

    server = {"mitglieder": [A]}

    def handler(request):
        if request.method == "GET" and request.url.path.endswith(f"projekt-{projekt_id}.vcf"):
            return httpx.Response(200, text=_gruppen_vcard(projekt_id, server["mitglieder"]))
        if request.method == "PUT":
            import re as _re
            server["mitglieder"] = [
                int(x) for x in _re.findall(r"urn:uuid:kontakt-(\d+)", request.content.decode())
            ]
            return httpx.Response(201)
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)

    radicale.push_projekt(tmp_db, projekt_id)          # Ausgangsstand, Schnappschuss {A}
    server["mitglieder"] = sorted(server["mitglieder"] + [B])   # Kollege in Kontakte.app
    queries.set_kontakt_projekte(tmp_db, C, [projekt_id])       # jemand im Browser
    radicale.push_projekt(tmp_db, projekt_id)

    # Schon der Push selbst muss zusammengefuehrt haben - ohne auf den Scan zu warten.
    assert set(server["mitglieder"]) == {A, B, C}
    assert _mitglieder(tmp_db, projekt_id) == {A, B, C}


def test_hintergrund_takt_ist_getrennt():
    """Kontakte.app haengt lokal an Radicale und wird engmaschig geprueft; der
    Mail-Eingang ist ein fremdes IMAP-Postfach und bleibt im Tagesrhythmus."""
    from web import main
    assert main._KONTAKTE_APP_INTERVALL == 5 * 60
    assert main._MAIL_INTERVALL == 24 * 60 * 60


# ── Feldaenderungen an bestehenden Kontakten (in Kontakte.app korrigiert) ─────

def _kontakt_mit_push(tmp_db, monkeypatch, **felder):
    """Legt einen Kontakt an und pusht ihn, damit ein Vergleichsstand existiert."""
    daten = {"vorname": "Anna", "nachname": "Muster", "kategorie": "Architektin",
             "telefonnummern": [{"typ": "Direkt", "nummer": "044 111 11 11"}],
             "emails": [{"typ": "Direkt", "email": "anna@beispiel.ch"}]}
    daten.update(felder)
    kontakt_id = queries.create_kontakt(tmp_db, daten)
    _mock_client(monkeypatch, lambda request: httpx.Response(201))
    radicale.push_kontakt(tmp_db, kontakt_id)
    return kontakt_id


def test_geaenderte_telefonnummer_wird_als_vorschlag_erfasst(tmp_db, monkeypatch):
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    gepusht = queries.hole_gepushte_vcard(tmp_db, kontakt_id)
    assert gepusht is not None
    geaendert = gepusht.replace("+41 44 111 11 11", "+41 44 222 22 22")

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text=geaendert)
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    ergebnis = kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

    assert ergebnis["neu"] == 1
    v = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")[0]
    assert v["rohdaten"]["typ"] == "aenderung"
    assert v["kontakt_id"] == kontakt_id
    felder = {u["feld"]: u for u in v["rohdaten"]["unterschiede"]}
    assert "Telefon" in felder
    assert "111 11 11" in felder["Telefon"]["alt"]
    assert "222 22 22" in felder["Telefon"]["neu"]


def test_uebernehmen_behaelt_die_funktion(tmp_db, monkeypatch):
    """Regressionsschutz: Rubrica schreibt die Funktion als CATEGORIES in die vCard,
    der Parser liest sie aber nie zurueck. Wuerde beim Uebernehmen die geparste vCard
    den Kontakt ersetzen, waere die Funktion - ein Pflichtfeld - danach leer."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    gepusht = queries.hole_gepushte_vcard(tmp_db, kontakt_id)
    geaendert = gepusht.replace("+41 44 111 11 11", "+41 44 222 22 22")

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text=geaendert)
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)
    v = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")[0]
    kontakte_app_intake.bestaetige_aenderungs_vorschlag(tmp_db, v)

    kontakt = queries.get_kontakt(tmp_db, kontakt_id)
    assert kontakt["kategorie"] == "Architektin"     # NICHT geleert
    assert "222 22 22" in kontakt["telefonnummern"][0]["nummer"]
    assert kontakt["vorname"] == "Anna"


def test_unveraenderte_vcard_erzeugt_keinen_vorschlag(tmp_db, monkeypatch):
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    gepusht = queries.hole_gepushte_vcard(tmp_db, kontakt_id)

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text=gepusht)
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    ergebnis = kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

    assert ergebnis["neu"] == 0
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app") == []


def test_dieselbe_aenderung_erzeugt_nur_einen_vorschlag(tmp_db, monkeypatch):
    """Der Lauf alle fuenf Minuten darf nicht bei jedem Durchgang denselben
    Vorschlag erneut anlegen, solange die Aenderung offen auf dem Server steht."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    geaendert = queries.hole_gepushte_vcard(tmp_db, kontakt_id).replace(
        "+41 44 111 11 11", "+41 44 222 22 22")

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text=geaendert)
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)
    kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

    assert len(queries.list_vorschlaege(tmp_db, quelle="kontakte_app")) == 1


def test_ohne_vergleichsstand_wird_nichts_erkannt(tmp_db, monkeypatch):
    """Altbestand aus einer Installation vor dieser Spalte: ohne Referenzpunkt
    waere jede Abweichung Spekulation."""
    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    _mock_client(monkeypatch, lambda request: httpx.Response(200, text="BEGIN:VCARD\r\nEND:VCARD\r\n"))
    ergebnis = kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)
    assert ergebnis["geprueft"] == 0 and ergebnis["neu"] == 0


def test_fehlgeschlagener_push_setzt_keinen_vergleichsstand(tmp_db, monkeypatch):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    _mock_client(monkeypatch, lambda request: httpx.Response(500))
    radicale.push_kontakt(tmp_db, kontakt_id)
    assert queries.hole_gepushte_vcard(tmp_db, kontakt_id) is None


# ── Loeschungen, Umbenennung, nachtraegliche Korrektur ───────────────────────

def test_in_kontakte_app_geloeschter_kontakt_wird_wiederhergestellt(tmp_db, monkeypatch):
    """Nutzer-Entscheid nach dem Abnahmetest: Loeschen von Kontakten geht nur noch im
    Browser. Verschwindet eine Karte aus Kontakte.app, schreibt Rubrica sie wieder
    hin, statt einen Vorschlag mit "Loeschen"/"Behalten" vorzulegen - dieser Weg war
    der stoerungsanfaelligste des ganzen Abgleichs und "Behalten" stellte den Kontakt
    nachweislich nicht wieder her."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)

    gesendet = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesendet.append((request.method, request.url.path))
        return httpx.Response(404) if request.method == "GET" else httpx.Response(201)

    _mock_client(monkeypatch, handler)
    ergebnis = kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

    assert ergebnis["wiederhergestellt"] == 1
    assert ergebnis["neu"] == 0
    assert ("PUT", f"/a/kontakt-{kontakt_id}.vcf") in gesendet
    # Kein Loeschvorschlag mehr - es gibt nichts zu entscheiden.
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app") == []
    # Und der Kontakt steht unveraendert in Rubrica.
    assert queries.get_kontakt(tmp_db, kontakt_id) is not None


def test_in_kontakte_app_geloeschter_ordner_wird_wiederhergestellt(tmp_db, monkeypatch):
    """Nutzer-Vorgabe: "wenn man lokal loescht soll es diese aenderung nie annehmen,
    loeschen geht nur vom browser" - fuer Ordner genauso wie fuer Kontakte."""
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    queries.setze_gepushte_mitglieder(tmp_db, projekt_id, [k1])

    gesendet = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesendet.append((request.method, request.url.path))
        return httpx.Response(404) if request.method == "GET" else httpx.Response(201)

    _mock_client(monkeypatch, handler)
    ergebnis = kontakte_app_intake.pruefe_ordner_mitgliedschaften(tmp_db)

    assert ergebnis["wiederhergestellt"] == 1
    assert ("PUT", f"/a/projekt-{projekt_id}.vcf") in gesendet
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app") == []
    assert any(o["id"] == projekt_id for o in queries.list_projekte(tmp_db))


def test_in_kontakte_app_umbenannter_ordner_wird_uebernommen(tmp_db, monkeypatch):
    """Umbenennen aendert keine Kontaktdaten - wirkt daher direkt, wie das
    Verschieben in Ordner. Vorher wurde es beim naechsten Push rueckgaengig gemacht."""
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle Nord")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    queries.setze_gepushte_mitglieder(tmp_db, projekt_id, [k1])

    def handler(request):
        if request.method == "GET":
            text = _gruppen_vcard(projekt_id, [k1]).replace("FN:Testordner", "FN:Baustelle Süd")
            return httpx.Response(200, text=text)
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    ergebnis = kontakte_app_intake.pruefe_ordner_mitgliedschaften(tmp_db)

    assert ergebnis["umbenannt"] == 1
    assert queries.list_projekte(tmp_db)[0]["name"] == "Baustelle Süd"


def test_korrektur_an_offenem_vorschlag_wird_nachgezogen(tmp_db, monkeypatch):
    """Korrigiert jemand den Tippfehler in Kontakte.app, bevor freigegeben wurde,
    muss der Vorschlag mitziehen - sonst wird die alte Fassung angelegt und die
    Korrektur verschwindet mit der geloeschten fremden vCard."""
    vc = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:NEU-1\r\nFN:Max Tipfehler\r\n"
          "N:Tipfehler;Max;;;\r\nEND:VCARD\r\n")
    srv = {"NEU-1.vcf": vc}

    def handler(request):
        pfad = request.url.path.rsplit("/", 1)[-1]
        if request.method == "PROPFIND":
            hrefs = "".join(f"<response><href>/a/{n}</href></response>" for n in srv)
            return httpx.Response(207, text=f"<multistatus>{hrefs}</multistatus>")
        if request.method == "GET":
            return httpx.Response(200, text=srv[pfad]) if pfad in srv else httpx.Response(404)
        return httpx.Response(201)

    _mock_client(monkeypatch, handler)
    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app")[0]["rohdaten"]["nachname"] == "Tipfehler"

    srv["NEU-1.vcf"] = vc.replace("Tipfehler", "Muster")
    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis["aktualisiert"] == 1
    offene = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert len(offene) == 1                      # kein zweiter Vorschlag
    assert offene[0]["rohdaten"]["nachname"] == "Muster"


def test_neuer_ordner_mit_bestehendem_kontakt_behaelt_zuordnung(tmp_db, monkeypatch):
    """Regression (Nutzer-Meldung beim ersten Praxistest): legt jemand in Kontakte.app
    einen neuen Ordner an und zieht einen BESTEHENDEN Rubrica-Kontakt hinein, ging die
    Zuordnung verloren - _ordner_rohdaten filterte alle kontakt-N-Mitglieder heraus,
    weil die Logik nur auf fremde Neuanlagen ausgelegt war. Der Ordner entstand leer."""
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    srv = {}

    def handler(request):
        pfad = request.url.path.rsplit("/", 1)[-1]
        if request.method == "PROPFIND":
            hrefs = "".join(f"<response><href>/a/{n}</href></response>" for n in srv)
            return httpx.Response(207, text=f"<multistatus>{hrefs}</multistatus>")
        if request.method == "GET":
            return httpx.Response(200, text=srv[pfad]) if pfad in srv else httpx.Response(404)
        if request.method == "PUT":
            srv[pfad] = request.content.decode()
            return httpx.Response(201)
        return httpx.Response(204)

    _mock_client(monkeypatch, handler)
    radicale.push_kontakt(tmp_db, kontakt_id)

    srv["NEUE-GRUPPE.vcf"] = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:NEUE-GRUPPE\r\nFN:Neubau Seestrasse\r\n"
        "X-ADDRESSBOOKSERVER-KIND:group\r\n"
        f"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:kontakt-{kontakt_id}\r\nEND:VCARD\r\n")

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    v = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")[0]
    assert v["rohdaten"]["mitglieder_kontakt_ids"] == [kontakt_id]

    projekt_id = kontakte_app_intake.bestaetige_ordner_vorschlag(tmp_db, v)

    assert _mitglieder(tmp_db, projekt_id) == {kontakt_id}


def test_alle_vcard_felder_werden_als_aenderung_erkannt(tmp_db, monkeypatch):
    """Nutzer-Vorgabe: in Kontakte.app soll sich JEDES Feld aendern lassen und jede
    Aenderung als Vorschlag ankommen. Deckt alle Feldarten ab, die eine vCard traegt,
    inklusive einer reinen Umkategorisierung (Direkt -> Privat)."""
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster", "firma": "Alt AG", "rolle": "Bauleiterin",
        "kategorie": "Architektin", "notizen": "alte Notiz",
        "telefonnummern": [{"typ": "Direkt", "nummer": "044 111 11 11"}],
        "emails": [{"typ": "Direkt", "email": "alt@beispiel.ch"}],
        "adressen": [{"typ": "arbeit", "strasse": "Altweg 1", "plz": "8000", "ort": "Zürich",
                      "region": "", "land": ""}],
        "urls": [{"typ": "homepage", "url": "www.alt.ch"}]})
    _mock_client(monkeypatch, lambda request: httpx.Response(201))
    radicale.push_kontakt(tmp_db, kontakt_id)
    basis = queries.hole_gepushte_vcard(tmp_db, kontakt_id)

    faelle = [
        ("Firma", "ORG:Alt AG", "ORG:Neu AG"),
        ("Rolle", "TITLE:Bauleiterin", "TITLE:Projektleiterin"),
        ("Notizen", "NOTE:alte Notiz", "NOTE:neue Notiz"),
        ("E-Mail", "alt@beispiel.ch", "neu@beispiel.ch"),
        ("Adresse", "Altweg 1", "Neuweg 9"),
        ("Web", "www.alt.ch", "www.neu.ch"),
        ("Vorname", "N:Muster;Anna", "N:Muster;Anita"),
        # Die Kategorie steht als X-ABLabel in der Karte (siehe
        # radicale._beschriftete_zeilen), nicht als TYPE-Parameter.
        ("Telefon", "X-ABLabel:Direkt\r\nitem2", "X-ABLabel:Privat\r\nitem2"),
    ]
    for feld, alt, neu in faelle:
        for v in queries.list_vorschlaege(tmp_db, quelle="kontakte_app"):
            queries.set_vorschlag_status(tmp_db, v["id"], "abgelehnt")
        geaendert = basis.replace(alt, neu)
        assert geaendert != basis, f"{feld}: Testdaten greifen nicht"
        _mock_client(monkeypatch, lambda r, t=geaendert: (
            httpx.Response(200, text=t) if r.method == "GET" else httpx.Response(201)))

        ergebnis = kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

        assert ergebnis["neu"] == 1, f"{feld} wurde nicht als Aenderung erkannt"
        offen = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")[0]
        assert feld in [u["feld"] for u in offen["rohdaten"]["unterschiede"]], \
            f"{feld} fehlt in der Gegenueberstellung"


def test_umkategorisierung_ist_in_der_anzeige_erkennbar(tmp_db, monkeypatch):
    """Ohne die Kategorie im Anzeigetext staende bei einer reinen Umstellung
    (Direkt -> Privat) links und rechts derselbe Wert - die Gegenueberstellung
    saehe aus wie ein Fehler."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    geaendert = queries.hole_gepushte_vcard(tmp_db, kontakt_id).replace(
        "X-ABLabel:Direkt\r\nitem2", "X-ABLabel:Privat\r\nitem2")

    _mock_client(monkeypatch, lambda r: (
        httpx.Response(200, text=geaendert) if r.method == "GET" else httpx.Response(201)))
    kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

    u = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")[0]["rohdaten"]["unterschiede"][0]
    assert u["alt"] != u["neu"]
    assert "Direkt" in u["alt"] and "Privat" in u["neu"]


def test_andere_schreibweise_ist_keine_aenderung(tmp_db, monkeypatch):
    """Regression (Nutzer-Meldung): "zeigt die telefonnummer als geaendert an obwohl
    ich daran nicht geaendert habe und es auch immer noch die gleichen zahlen sind".
    Kontakte.app schreibt Werte in eigener Schreibweise zurueck - das darf keine
    Aenderung ausloesen."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    basis = queries.hole_gepushte_vcard(tmp_db, kontakt_id)

    # gleiche Ziffern, andere Formatierung; Mail in anderer Gross-/Kleinschreibung
    anders = (basis.replace("+41 44 111 11 11", "+41-44-111-11-11")
                   .replace("anna@beispiel.ch", "Anna@Beispiel.CH"))
    assert anders != basis

    _mock_client(monkeypatch, lambda r: (
        httpx.Response(200, text=anders) if r.method == "GET" else httpx.Response(201)))
    ergebnis = kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

    assert ergebnis["neu"] == 0, "reine Schreibweise wurde faelschlich als Aenderung gemeldet"
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app") == []


def test_echte_nummernaenderung_wird_weiterhin_erkannt(tmp_db, monkeypatch):
    """Gegenprobe zur Normalisierung: andere Ziffern muessen weiterhin auffallen."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    anders = queries.hole_gepushte_vcard(tmp_db, kontakt_id).replace(
        "+41 44 111 11 11", "+41 44 222 22 22")

    _mock_client(monkeypatch, lambda r: (
        httpx.Response(200, text=anders) if r.method == "GET" else httpx.Response(201)))

    assert kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)["neu"] == 1


def test_name_mit_zusatz_wird_erkannt(tmp_db):
    """Nutzer-Meldung am echten Beispiel: eine vollstaendige Signatur kam als
    Mail-Vorschlag an, der Name fehlte aber komplett. Ursache war die Regel "jedes
    Wort muss gross geschrieben sein" - "Christoph von Arx" fiel durch."""
    from importer.signatur import parse_signatur
    d = parse_signatur(
        "Freundliche Grüsse\nChristoph von Arx\nDipl. Ing. Landschaftsarchitekt FH BSLA SIA\n\n"
        "beispiel landschaftsarchitektur gmbh\nmusterplatz 1\n4500 Musterhausen\n"
        "tel 032 111 11 11\nmail@beispiel.ch")
    assert d["vorname"] == "Christoph"
    assert d["nachname"] == "von Arx"     # Zusatz gehoert zum Nachnamen


def test_ueberwachungs_abdeckung_zeigt_luecke(tmp_db, monkeypatch):
    """Ohne Vergleichsstand bleibt eine Loeschung/Aenderung unbemerkt - das ist eine
    stille Ursache, deshalb in den Einstellungen sichtbar gemacht."""
    queries.create_kontakt(tmp_db, {"vorname": "Ohne", "nachname": "Push"})
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Mit", "nachname": "Push"})
    _mock_client(monkeypatch, lambda r: httpx.Response(201))
    radicale.push_kontakt(tmp_db, kontakt_id)

    a = queries.ueberwachungs_abdeckung(tmp_db)
    assert a == {"gesamt": 2, "ueberwacht": 1}


def test_hinfaelliger_aenderungsvorschlag_wird_zurueckgezogen(tmp_db, monkeypatch):
    """Nutzer-Meldung: nach einem Fehler in der Kategorie-Rueckrichtung standen
    reihenweise Vorschlaege in der Liste, die keine echte Aenderung waren. Sobald
    der Unterschied nicht mehr besteht, muss der Vorschlag von selbst verschwinden -
    sonst muesste man Hunderte davon einzeln wegklicken."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    basis = queries.hole_gepushte_vcard(tmp_db, kontakt_id)
    geaendert = basis.replace("+41 44 111 11 11", "+41 44 222 22 22")

    _mock_client(monkeypatch, lambda r: (
        httpx.Response(200, text=geaendert) if r.method == "GET" else httpx.Response(201)))
    assert kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)["neu"] == 1
    assert len(queries.list_vorschlaege(tmp_db, quelle="kontakte_app")) == 1

    # Der Server steht wieder auf dem Vergleichsstand - der Vorschlag ist gegenstandslos.
    _mock_client(monkeypatch, lambda r: (
        httpx.Response(200, text=basis) if r.method == "GET" else httpx.Response(201)))
    ergebnis = kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

    assert ergebnis["zurueckgezogen"] == 1
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app") == []


def test_neue_andere_aenderung_ersetzt_den_alten_vorschlag(tmp_db, monkeypatch):
    """Sonst stuenden zwei Vorschlaege zum selben Kontakt in der Liste, von denen
    einer einen laengst ueberholten Stand vorschlaegt."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    basis = queries.hole_gepushte_vcard(tmp_db, kontakt_id)

    for neue_nummer in ("+41 44 222 22 22", "+41 44 333 33 33"):
        geaendert = basis.replace("+41 44 111 11 11", neue_nummer)
        assert geaendert != basis
        _mock_client(monkeypatch, lambda r, t=geaendert: (
            httpx.Response(200, text=t) if r.method == "GET" else httpx.Response(201)))
        kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

    offen = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert len(offen) == 1
    assert "+41 44 333 33 33" in str(offen[0]["rohdaten"]["unterschiede"])


_LEERE_VCARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:NEU-LEER\r\nN:;;;;\r\nFN:\r\nEND:VCARD\r\n"
)


def test_leere_karte_erzeugt_keinen_vorschlag(tmp_db, monkeypatch):
    """Regression (Nutzer-Meldung: "sie erscheinen aber sie sind leer"). Kontakte.app
    legt die Karte schon beim Klick auf "+" an und schiebt sie sofort auf den
    Server - zu dem Zeitpunkt steht noch kein einziges Feld darin."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["NEU-LEER.vcf"]))
        return httpx.Response(200, text=_LEERE_VCARD)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis["neu"] == 0
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app") == []


def test_karte_wird_nach_dem_ausfuellen_doch_noch_erfasst(tmp_db, monkeypatch):
    """Die Karte wird uebersprungen, nicht dauerhaft verworfen."""
    inhalt = {"text": _LEERE_VCARD}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["NEU-LEER.vcf"]))
        return httpx.Response(200, text=inhalt["text"])

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    inhalt["text"] = _LEERE_VCARD.replace("N:;;;;\r\nFN:\r\n", "N:Muster;Anna;;;\r\nFN:Anna Muster\r\n")
    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis["neu"] == 1
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app")[0]["rohdaten"]["vorname"] == "Anna"


def test_geloeschte_karte_zieht_offenen_vorschlag_zurueck(tmp_db, monkeypatch):
    """Wer den in Kontakte.app angelegten Kontakt dort wieder loescht, bevor ihn
    jemand im Buero bestaetigt, laesst sonst einen Vorschlag stehen, der auf eine
    nicht mehr existierende Karte zeigt."""
    namen = {"liste": ["ABC-123-FREMD.vcf"]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(namen["liste"]))
        return httpx.Response(200, text=_FREMDE_VCARD)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    assert len(queries.list_vorschlaege(tmp_db, quelle="kontakte_app")) == 1

    namen["liste"] = []
    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis["zurueckgezogen"] == 1
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app") == []


def test_verbindungsfehler_zieht_keine_vorschlaege_zurueck(tmp_db, monkeypatch):
    """Sonst raeumte ein einzelner Aussetzer beim PROPFIND saemtliche offenen
    Vorschlaege ab - die leere Liste waere faelschlich als "alles weg" gelesen."""
    zustand = {"propfind_ok": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            if not zustand["propfind_ok"]:
                return httpx.Response(503)
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        return httpx.Response(200, text=_FREMDE_VCARD)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    zustand["propfind_ok"] = False
    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis["zurueckgezogen"] == 0
    assert len(queries.list_vorschlaege(tmp_db, quelle="kontakte_app")) == 1


def test_serverstand_der_schon_in_rubrica_steht_ist_keine_aenderung(tmp_db, monkeypatch):
    """Regression (Nutzer-Meldung: reihenweise Vorschläge "Privat -> Direkt").
    Rubricas eigene Kategorie-Umstellung hat den Datenbankstand verändert; der
    Schnappschuss stammte noch von davor, der Server hatte den neuen Stand schon.
    Der Vergleich Schnappschuss/Server sah darin eine Änderung aus Kontakte.app -
    obwohl der Server genau das zeigte, was in Rubrica ohnehin steht."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    veralteter_schnappschuss = queries.hole_gepushte_vcard(tmp_db, kontakt_id).replace(
        "X-ABLabel:Direkt\r\nitem2", "X-ABLabel:Privat\r\nitem2")
    queries.setze_gepushte_vcard(tmp_db, kontakt_id, veralteter_schnappschuss)
    aktuell = radicale.kontakt_zu_vcard(queries.get_kontakt(tmp_db, kontakt_id))

    _mock_client(monkeypatch, lambda r: (
        httpx.Response(200, text=aktuell) if r.method == "GET" else httpx.Response(201)))
    ergebnis = kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)

    assert ergebnis["neu"] == 0
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app") == []


def test_echte_aenderung_wird_davon_nicht_verdeckt(tmp_db, monkeypatch):
    """Gegenprobe: weicht der Server auch vom Datenbankstand ab, ist es eine echte
    Änderung aus Kontakte.app und muss weiterhin als Vorschlag kommen."""
    kontakt_id = _kontakt_mit_push(tmp_db, monkeypatch)
    geaendert = queries.hole_gepushte_vcard(tmp_db, kontakt_id).replace(
        "+41 44 111 11 11", "+41 44 999 99 99")

    _mock_client(monkeypatch, lambda r: (
        httpx.Response(200, text=geaendert) if r.method == "GET" else httpx.Response(201)))

    assert kontakte_app_intake.pruefe_kontakt_aenderungen(tmp_db)["neu"] == 1


def test_in_kontakte_app_angelegter_kontakt_behaelt_seinen_ordner(tmp_db, monkeypatch):
    """Regression (Nutzer-Meldung im Abnahmetest): "zuordnung fehlt (ich habe sie in
    einem ordner erstellt gehabt)". Apple trägt einen dort neu angelegten Kontakt mit
    seiner eigenen UID in die Gruppen-vCard ein. Rubrica baute die Gruppe beim
    nächsten Push komplett aus der Datenbank neu auf - die kennt diese UID nicht, die
    Zugehörigkeit war weg, bevor der Scan sie lesen konnte."""
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle Muster")
    gruppe = {"text": (
        f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:projekt-{projekt_id}\r\nFN:Baustelle Muster\r\n"
        "X-ADDRESSBOOKSERVER-KIND:group\r\n"
        "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:ABC-123-FREMD\r\nEND:VCARD\r\n")}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        if request.method == "PUT":
            gruppe["text"] = request.content.decode()
            return httpx.Response(201)
        if request.url.path.endswith("ABC-123-FREMD.vcf"):
            return httpx.Response(200, text=_FREMDE_VCARD)
        return httpx.Response(200, text=gruppe["text"])

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert vorschlaege[0]["rohdaten"]["erkannte_ordner_ids"] == [projekt_id]

    # Ein Push des Ordners (z.B. weil im Browser jemand etwas anderes geaendert hat)
    # darf die noch offene Mitgliedschaft nicht herausreissen.
    radicale.push_projekt(tmp_db, projekt_id)
    assert "urn:uuid:ABC-123-FREMD" in gruppe["text"]

    # Und der Scan findet sie danach immer noch.
    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app")[0]["rohdaten"]["erkannte_ordner_ids"] \
        == [projekt_id]


def test_entschiedener_vorschlag_hinterlaesst_keinen_verweis(tmp_db, monkeypatch):
    """Gegenprobe: nach dem Entscheid darf die fremde UID nicht ewig weitergeschrieben
    werden - sonst zeigt die Gruppe dauerhaft auf eine Karte, die es nicht mehr gibt."""
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle Muster")
    gruppe = {"text": (
        f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:projekt-{projekt_id}\r\nFN:Baustelle Muster\r\n"
        "X-ADDRESSBOOKSERVER-KIND:group\r\n"
        "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:ABC-123-FREMD\r\nEND:VCARD\r\n")}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            gruppe["text"] = request.content.decode()
            return httpx.Response(201)
        return httpx.Response(200, text=gruppe["text"])

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    # Kein offener Vorschlag zu dieser UID -> es gibt nichts mehr zu bewahren.
    radicale.push_projekt(tmp_db, projekt_id)
    assert "ABC-123-FREMD" not in gruppe["text"]


def test_zwei_karten_derselben_person_ergeben_einen_vorschlag(tmp_db, monkeypatch):
    """Regression (Nutzer-Meldung im Abnahmetest): "Vorschläge kommen an, aber
    doppelt". Der Dublettenschutz fragte nur nach dem Dateinamen; legt Kontakte.app
    beim Speichern eine zweite Karte mit neuer UID an, sind es zwei Dateien mit
    identischem Inhalt - und damit zwei Vorschläge über dieselbe Person."""
    zweite = _FREMDE_VCARD.replace("UID:ABC-123-FREMD", "UID:DEF-456-FREMD")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf", "DEF-456-FREMD.vcf"]))
        if request.url.path.endswith("DEF-456-FREMD.vcf"):
            return httpx.Response(200, text=zweite)
        return httpx.Response(200, text=_FREMDE_VCARD)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis["neu"] == 1
    assert ergebnis["zusammengefuehrt"] == 1
    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert len(vorschlaege) == 1
    # Beide Karten haengen am Vorschlag, damit keine als Karteileiche liegen bleibt.
    assert vorschlaege[0]["rohdaten"]["weitere_vcf_namen"] == ["DEF-456-FREMD.vcf"]


def test_zweitkarte_wird_nicht_bei_jedem_durchlauf_neu_betrachtet(tmp_db, monkeypatch):
    zweite = _FREMDE_VCARD.replace("UID:ABC-123-FREMD", "UID:DEF-456-FREMD")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf", "DEF-456-FREMD.vcf"]))
        if request.url.path.endswith("DEF-456-FREMD.vcf"):
            return httpx.Response(200, text=zweite)
        return httpx.Response(200, text=_FREMDE_VCARD)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    zweiter_lauf = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert zweiter_lauf["zusammengefuehrt"] == 0
    assert len(queries.list_vorschlaege(tmp_db, quelle="kontakte_app")) == 1


def test_verschiedene_personen_bleiben_zwei_vorschlaege(tmp_db, monkeypatch):
    """Gegenprobe: die Zusammenführung darf nicht zwei echte Neuzugänge verschlucken."""
    andere = (_FREMDE_VCARD.replace("UID:ABC-123-FREMD", "UID:DEF-456-FREMD")
                            .replace("Max", "Moritz").replace("max@", "moritz@"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf", "DEF-456-FREMD.vcf"]))
        if request.url.path.endswith("DEF-456-FREMD.vcf"):
            return httpx.Response(200, text=andere)
        return httpx.Response(200, text=_FREMDE_VCARD)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis["neu"] == 2
    assert len(queries.list_vorschlaege(tmp_db, quelle="kontakte_app")) == 2


def test_rohtext_der_karteikarte_wird_mitgefuehrt(tmp_db, monkeypatch):
    """Damit sich bei einer Meldung wie "die Telefonnummer ist leer" nachsehen
    lässt, was Kontakte.app überhaupt geschickt hat, statt zu raten."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        return httpx.Response(200, text=_FREMDE_VCARD)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    rohtext = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")[0]["rohdaten"]["kontakte_app_rohtext"]
    assert "BEGIN:VCARD" in rohtext and "Mustermann" in rohtext
