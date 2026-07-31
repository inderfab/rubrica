import httpx
from fastapi.testclient import TestClient

from db import queries
from sync import radicale
from web.main import app


def _client():
    return TestClient(app)


def test_seite_zeigt_offene_mail_und_kontakte_app_vorschlaege(tmp_db):
    queries.create_vorschlag(tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []},
                              quelle="mail")
    queries.create_vorschlag(tmp_db, {"vorname": "Chris", "nachname": "Contact", "telefonnummern": [], "emails": []},
                              quelle="kontakte_app")
    queries.create_vorschlag(tmp_db, {"vorname": "Bruno", "nachname": "Beispiel", "telefonnummern": [], "emails": []},
                              quelle="import")

    r = _client().get("/vorschlaege")
    assert r.status_code == 200
    assert "Anna" in r.text
    assert "Chris" in r.text
    assert "Bruno" not in r.text


def test_uebernehmen_legt_kontakt_an_und_schliesst_vorschlag(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )

    r = _client().post(f"/vorschlaege/{vorschlag_id}/uebernehmen", follow_redirects=False)
    assert r.status_code == 303

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert kontakte[0]["nachname"] == "Muster"
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []


def test_ablehnen_legt_keinen_kontakt_an(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )

    r = _client().post(f"/vorschlaege/{vorschlag_id}/ablehnen", follow_redirects=False)
    assert r.status_code == 303

    assert queries.list_kontakte(tmp_db) == []
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []
    assert queries.get_vorschlag(tmp_db, vorschlag_id)["status"] == "abgelehnt"


def test_bearbeiten_flyover_zeigt_formular_mit_vorbefuellten_werten(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().get(f"/vorschlaege/{vorschlag_id}/bearbeiten-flyover")
    assert r.status_code == 200
    assert 'value="Anna"' in r.text
    assert 'value="Muster"' in r.text


def test_bearbeiten_flyover_unbekannter_vorschlag_ist_404(tmp_db):
    r = _client().get("/vorschlaege/999999/bearbeiten-flyover")
    assert r.status_code == 404


def test_uebernehmen_bearbeitet_speichert_korrigierte_werte(tmp_db):
    projekt_id = queries.get_or_create_projekt(tmp_db, "Testprojekt")
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().post(f"/vorschlaege/{vorschlag_id}/uebernehmen-bearbeitet", data={
        "vorname": "Anna", "nachname": "Korrigiert", "firma": "", "kategorie": "Geologe", "rolle": "",
        "telefon_typ": "Direkt", "telefon_nummer": "079 111 22 33",
        "email_typ": "Direkt", "email_adresse": "anna@beispiel.ch",
        "adresse_typ": "arbeit", "adresse_strasse": "Musterstrasse 1", "adresse_plz": "8000", "adresse_ort": "Zürich",
        "adresse_region": "", "adresse_land": "", "ordner_ids": str(projekt_id),
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/vorschlaege"

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert kontakte[0]["nachname"] == "Korrigiert"
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []


def test_moeglicher_duplikat_zeigt_bestaetigungs_abfrage(tmp_db):
    # Regression: Nutzer-Feedback - beim Uebernehmen eines Mail-Vorschlags mit
    # bereits bekanntem Namen (aber anderer Mailadresse) kam keine Rueckfrage, im
    # Gegensatz zur manuellen Kontakt-Neuanlage. finde_match() erkennt den
    # Duplikat-Kandidaten selbst schon korrekt (siehe kontakt_id auf dem Vorschlag) -
    # es fehlte nur die sichtbare Warnung + Bestaetigung vor dem Zusammenfuehren.
    bestehender_id = queries.create_kontakt(tmp_db, {"vorname": "Bruno", "nachname": "Beispiel"})
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Bruno", "nachname": "Beispiel", "telefonnummern": [],
                 "emails": [{"typ": "Direkt", "email": "neu@beispiel.ch"}]},
        kontakt_id=bestehender_id, quelle="mail",
    )

    r = _client().get("/vorschlaege")
    assert r.status_code == 200
    assert "Möglicher Duplikat" in r.text
    assert "confirm(" in r.text
    assert f"/vorschlaege/{vorschlag_id}/uebernehmen" in r.text
    assert f"/kontakte/{bestehender_id}/bearbeiten" in r.text


def test_ohne_duplikat_keine_bestaetigungs_abfrage(tmp_db):
    queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().get("/vorschlaege")
    assert r.status_code == 200
    assert "Möglicher Duplikat" not in r.text


def test_jetzt_pruefen_route_kombiniert_beide_quellen(tmp_db, monkeypatch):
    import kontakte_app_intake
    import mail_intake
    monkeypatch.setattr(mail_intake, "pruefe_und_beschreibe",
                         lambda conn: "3 Nachrichten geprüft, 1 neue Kontaktvorschläge angelegt.")
    monkeypatch.setattr(kontakte_app_intake, "pruefe_und_beschreibe",
                         lambda conn: "2 neue Kontakte.app-Einträge geprüft, 1 neue Kontaktvorschläge angelegt.")

    r = _client().post("/vorschlaege/pruefen", follow_redirects=False)
    assert r.status_code == 303
    assert "meldung=" in r.headers["location"]

    r2 = _client().get(r.headers["location"])
    assert "3 Nachrichten geprüft" in r2.text
    assert "2 neue Kontakte.app-Einträge geprüft" in r2.text


def test_uebernehmen_weist_erkannte_ordner_zu_und_loescht_fremde_vcard(tmp_db, monkeypatch):
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle Muster")
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {
            "vorname": "Chris", "nachname": "Contact", "telefonnummern": [], "emails": [],
            "erkannte_ordner_ids": [projekt_id], "kontakte_app_vcf_name": "ABC-123-FREMD.vcf",
        },
        quelle="kontakte_app",
    )

    geloescht = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            geloescht.append(request.url.path)
            return httpx.Response(204)
        return httpx.Response(201)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    r = _client().post(f"/vorschlaege/{vorschlag_id}/uebernehmen", follow_redirects=False)
    assert r.status_code == 303

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert [p["id"] for p in kontakte[0]["projekte"]] == [projekt_id]
    assert "/a/ABC-123-FREMD.vcf" in geloescht
