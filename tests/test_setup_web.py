import sqlite3

from fastapi.testclient import TestClient

from config import settings
from db import queries
from sync import radicale
from web import setup as setup_modul
from web.main import app


def _lokal_bypass(monkeypatch):
    """TestClient simuliert keinen echten localhost-Request (Host ist "testclient") -
    fuer Funktionstests wird der Lokal-Guard deshalb bewusst umgangen. Der Guard
    selbst wird separat getestet (siehe test_setup_blockiert_nicht_lokale_anfragen)."""
    monkeypatch.setattr(setup_modul, "_nur_lokal", lambda request: None)


def test_setup_blockiert_nicht_lokale_anfragen(tmp_db):
    # Ohne Bypass simuliert TestClient einen "testclient"-Host, keinen echten
    # localhost-Request - genau das soll der Guard abweisen.
    r = TestClient(app).get("/setup/1")
    assert r.status_code == 403


def test_setup_schritt1_zeigt_willkommen(tmp_db, monkeypatch):
    _lokal_bypass(monkeypatch)
    r = TestClient(app).get("/setup/1")
    assert r.status_code == 200
    assert "Willkommen" in r.text


def test_setup_schritt2_speichert_firmenname_und_leitet_weiter(tmp_db, monkeypatch, tmp_path):
    _lokal_bypass(monkeypatch)
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/setup/2", data={"export_firmenname": "Muster Architektur AG"},
                              follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/setup/3"
    assert settings.get("export.firmenname") == "Muster Architektur AG"


def test_setup_schritt3_speichert_eigene_domains(tmp_db, monkeypatch, tmp_path):
    _lokal_bypass(monkeypatch)
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/setup/3", data={"archivio_eigene_domains": "@Muster.ch, Andere.CH"},
                              follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/setup/4"
    assert settings.get("archivio.eigene_domains") == ["muster.ch", "andere.ch"]


def test_setup_schritt4_zeigt_carddav_zugangsdaten(tmp_db, monkeypatch):
    _lokal_bypass(monkeypatch)
    monkeypatch.setattr(settings, "_settings", {"radicale": {"password": "geheim123"}})

    r = TestClient(app).get("/setup/4")
    assert r.status_code == 200
    assert radicale.RADICALE_BENUTZER in r.text
    assert "geheim123" in r.text


def test_carddav_test_ohne_konfiguration_meldet_fehler(tmp_db, monkeypatch):
    _lokal_bypass(monkeypatch)
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": ""}})

    r = TestClient(app).post("/setup/carddav-test")
    assert r.status_code == 200
    daten = r.json()
    assert daten["ok"] is False


def test_carddav_test_meldet_erfolg_bei_207(tmp_db, monkeypatch):
    _lokal_bypass(monkeypatch)

    class _FakeResponse:
        status_code = 207

    class _FakeClient:
        def request(self, methode, pfad, headers=None):
            return _FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(radicale, "_client", lambda: _FakeClient())

    r = TestClient(app).post("/setup/carddav-test")
    assert r.status_code == 200
    daten = r.json()
    assert daten["ok"] is True
    assert "207" in daten["detail"]


def test_setup_schritt6_speichert_und_zeigt_fehlende_datei(tmp_db, monkeypatch, tmp_path):
    _lokal_bypass(monkeypatch)
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/setup/6", data={
        "archivio_signatur_db_path": "/pfad/existiert/nicht.db", "archivio_min_mails": "3",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert settings.get("archivio.signatur_db_path") == "/pfad/existiert/nicht.db"
    assert settings.get("archivio.min_mails") == 3

    r2 = TestClient(app).get("/setup/6?gespeichert=1")
    assert "Keine Datei" in r2.text


def test_setup_schritt6_zeigt_anzahl_bei_vorhandener_datei(tmp_db, monkeypatch, tmp_path):
    _lokal_bypass(monkeypatch)
    signatur_db = tmp_path / "archivio.db"
    conn = sqlite3.connect(signatur_db)
    conn.execute("CREATE TABLE signatur_quelle (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO signatur_quelle DEFAULT VALUES")
    conn.execute("INSERT INTO signatur_quelle DEFAULT VALUES")
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": str(signatur_db)}})

    r = TestClient(app).get("/setup/6")
    assert r.status_code == 200
    assert "2 Einträge" in r.text


def test_setup_schritt7_setzt_completed_und_leitet_zu_kontakte(tmp_db, monkeypatch, tmp_path):
    _lokal_bypass(monkeypatch)
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/setup/7", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/kontakte"
    assert settings.get("setup.completed") is True


def test_setup_erforderlich_ohne_kontakte_und_ohne_marker(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {})
    assert setup_modul is not None  # Modul-Import beruehrt web.shared, kein zirkulaerer Import
    from web.shared import _setup_erforderlich
    assert _setup_erforderlich() is True


def test_setup_erforderlich_false_wenn_kontakte_vorhanden_setzt_marker(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})
    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})

    from web.shared import _setup_erforderlich
    assert _setup_erforderlich() is False
    assert settings.get("setup.completed") is True


def test_root_leitet_auf_setup_um_wenn_erforderlich(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {})
    r = TestClient(app).get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/setup/1"


def test_root_leitet_auf_kontakte_um_wenn_bereits_eingerichtet(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"setup": {"completed": True}})
    r = TestClient(app).get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/kontakte"
