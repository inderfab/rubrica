from fastapi.testclient import TestClient

from config import settings
from web.main import app


def test_einstellungen_formular_zeigt_aktuellen_wert(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": "/pfad/archivio.db", "min_mails": 3}})
    r = TestClient(app).get("/einstellungen")
    assert r.status_code == 200
    assert "/pfad/archivio.db" in r.text
    assert 'value="3"' in r.text


def test_einstellungen_speichern_schreibt_config(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/einstellungen", data={
        "archivio_db_path": "/neuer/pfad/archivio.db",
        "archivio_min_mails": "5",
        "backup_pfad": "/Volumes/NAS/Rubrica-Backup",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "gespeichert=1" in r.headers["location"]

    assert settings.get("archivio.db_path") == "/neuer/pfad/archivio.db"
    assert settings.get("archivio.min_mails") == 5
    assert settings.get("backup.pfad") == "/Volumes/NAS/Rubrica-Backup"


def test_einstellungen_speichern_zeigt_bestaetigung(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    client = TestClient(app)
    client.post("/einstellungen", data={"archivio_db_path": "", "archivio_min_mails": "2"})
    r = client.get("/einstellungen?gespeichert=1")
    assert "Gespeichert" in r.text
