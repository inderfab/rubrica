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
    assert ergebnis == {"aktiv": False, "geprueft": 0, "neu": 0, "fehler": 0}


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

    assert ergebnis == {"aktiv": True, "geprueft": 1, "neu": 1, "fehler": 0}
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
