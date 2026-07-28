from fastapi.testclient import TestClient

from web import imports as imports_modul
from web.main import app


def test_import_form_zeigt_knopf_nur_lokal(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: True)
    r = TestClient(app).get("/import")
    assert 'id="import-kontakte-app-knopf"' in r.text


def test_import_form_versteckt_knopf_ueber_lan(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: False)
    r = TestClient(app).get("/import")
    assert 'id="import-kontakte-app-knopf"' not in r.text


def test_import_kontakte_app_blockiert_nicht_lokale_anfragen(tmp_db):
    # TestClient simuliert Host "testclient", kein echter localhost-Request.
    r = TestClient(app).post("/import/kontakte-app")
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_import_kontakte_app_meldet_erfolg(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: True)
    monkeypatch.setattr(imports_modul, "importiere_kontakte_app_und_synchronisiere", lambda conn: {
        "gefunden": 2, "gruppen_gefunden": 0, "importiert": 2, "fehler": 0,
        "ohne_uid": 0, "kontakte_gesamt": 2, "ordner_gesamt": 0,
    })

    r = TestClient(app).post("/import/kontakte-app")
    assert r.status_code == 200
    daten = r.json()
    assert daten["ok"] is True
    assert daten["importiert"] == 2
