from fastapi.testclient import TestClient

from web import import_status, imports as imports_modul
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
    assert r.json()["gestartet"] is False


def test_import_kontakte_app_startet_hintergrund_job(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: True)
    monkeypatch.setattr(import_status, "starten", lambda: True)

    r = TestClient(app).post("/import/kontakte-app")
    assert r.status_code == 200
    assert r.json() == {"gestartet": True}


def test_import_kontakte_app_status_meldet_fortschritt(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: True)
    monkeypatch.setattr(import_status, "status", lambda: {
        "laeuft": True, "phase": "synchronisiere", "verarbeitet": 2, "gesamt": 2,
        "fertig": False, "ergebnis": None, "fehler_meldung": None,
    })

    r = TestClient(app).get("/import/kontakte-app/status")
    assert r.status_code == 200
    daten = r.json()
    assert daten["laeuft"] is True
    assert daten["phase"] == "synchronisiere"


def test_import_kontakte_app_status_ueber_lan_meldet_nicht_laufend(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: False)
    r = TestClient(app).get("/import/kontakte-app/status")
    assert r.status_code == 200
    assert r.json()["laeuft"] is False


def test_zusammengefuehrte_duplikate_seite_zeigt_eingehende_und_bestehende_daten(tmp_db):
    from db import queries
    bestehender_id = queries.create_kontakt(tmp_db, {
        "vorname": "Peter", "nachname": "Kunz", "emails": [{"typ": "Direkt", "email": "peter@beispiel.ch"}],
    })
    queries.create_vorschlag(
        tmp_db, {"vorname": "Peter", "nachname": "Kunz", "emails": [{"typ": "Direkt", "email": "peter@beispiel.ch"}],
                 "telefonnummern": []},
        kontakt_id=bestehender_id, quelle="import",
    )
    queries.set_vorschlag_status(tmp_db, 1, "bestaetigt")

    r = TestClient(app).get("/import/zusammengefuehrte-duplikate")
    assert r.status_code == 200
    assert "Peter Kunz" in r.text
    assert f"/kontakte/{bestehender_id}/bearbeiten" in r.text


def test_zusammengefuehrte_duplikate_seite_ohne_ergebnisse(tmp_db):
    r = TestClient(app).get("/import/zusammengefuehrte-duplikate")
    assert r.status_code == 200
    assert "Keine Zusammenführungen gefunden" in r.text
