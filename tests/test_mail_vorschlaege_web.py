from fastapi.testclient import TestClient

from db import queries
from web.main import app


def _client():
    return TestClient(app)


def test_seite_zeigt_nur_offene_mail_vorschlaege(tmp_db):
    queries.create_vorschlag(tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []},
                              quelle="mail")
    queries.create_vorschlag(tmp_db, {"vorname": "Bruno", "nachname": "Beispiel", "telefonnummern": [], "emails": []},
                              quelle="import")

    r = _client().get("/mail-vorschlaege")
    assert r.status_code == 200
    assert "Anna" in r.text
    assert "Bruno" not in r.text


def test_uebernehmen_legt_kontakt_an_und_schliesst_vorschlag(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )

    r = _client().post(f"/mail-vorschlaege/{vorschlag_id}/uebernehmen", follow_redirects=False)
    assert r.status_code == 303

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert kontakte[0]["nachname"] == "Muster"
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []


def test_ablehnen_legt_keinen_kontakt_an(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )

    r = _client().post(f"/mail-vorschlaege/{vorschlag_id}/ablehnen", follow_redirects=False)
    assert r.status_code == 303

    assert queries.list_kontakte(tmp_db) == []
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []
    assert queries.get_vorschlag(tmp_db, vorschlag_id)["status"] == "abgelehnt"


def test_bearbeiten_flyover_zeigt_formular_mit_vorbefuellten_werten(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().get(f"/mail-vorschlaege/{vorschlag_id}/bearbeiten-flyover")
    assert r.status_code == 200
    assert 'value="Anna"' in r.text
    assert 'value="Muster"' in r.text


def test_bearbeiten_flyover_unbekannter_vorschlag_ist_404(tmp_db):
    r = _client().get("/mail-vorschlaege/999999/bearbeiten-flyover")
    assert r.status_code == 404


def test_uebernehmen_bearbeitet_speichert_korrigierte_werte(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().post(f"/mail-vorschlaege/{vorschlag_id}/uebernehmen-bearbeitet", data={
        "vorname": "Anna", "nachname": "Korrigiert", "firma": "", "kategorie": "", "rolle": "",
    }, follow_redirects=False)
    assert r.status_code == 303

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert kontakte[0]["nachname"] == "Korrigiert"
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []
