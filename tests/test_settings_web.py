import bcrypt
from fastapi.testclient import TestClient

from config import settings
from sync import htpasswd
from web.main import app


def test_einstellungen_formular_zeigt_aktuellen_wert(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": "/pfad/archivio.db", "min_mails": 3}})
    r = TestClient(app).get("/einstellungen")
    assert r.status_code == 200
    assert "/pfad/archivio.db" in r.text
    assert 'value="3"' in r.text


def test_radicale_sync_button_ohne_konfiguration_meldet_inaktiv(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": ""}})
    r = TestClient(app).post("/einstellungen/radicale-sync", follow_redirects=False)
    assert r.status_code == 303
    assert "sync=" in r.headers["location"]


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


def test_einstellungen_formular_zeigt_radicale_werte_im_klartext(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"radicale": {
        "base_url": "https://127.0.0.1:8443", "addressbook_path": "/pas/kontakte/",
        "username": "pas", "password": "geheim123", "verify_ssl": True,
    }})
    r = TestClient(app).get("/einstellungen")
    assert r.status_code == 200
    assert "https://127.0.0.1:8443" in r.text
    assert "/pas/kontakte/" in r.text
    assert "geheim123" in r.text


def test_einstellungen_speichern_schreibt_radicale_config(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/einstellungen", data={
        "radicale_base_url": "https://127.0.0.1:8443",
        "radicale_addressbook_path": "/pas/kontakte/",
        "radicale_username": "pas",
        "radicale_password": "neuespasswort",
        "radicale_verify_ssl": "on",
    }, follow_redirects=False)
    assert r.status_code == 303

    assert settings.get("radicale.base_url") == "https://127.0.0.1:8443"
    assert settings.get("radicale.addressbook_path") == "/pas/kontakte/"
    assert settings.get("radicale.username") == "pas"
    assert settings.get("radicale.password") == "neuespasswort"
    assert settings.get("radicale.verify_ssl") is True

    # Kernpunkt des Bugfixes: das Passwort muss auch in der htpasswd-Datei landen
    # (Server-Auth), nicht nur in config.yaml (Client-Push) - sonst schlaegt der
    # Login von Kontakte.app fehl.
    inhalt = htpasswd.htpasswd_pfad().read_text(encoding="utf-8").strip()
    login, digest = inhalt.split(":", maxsplit=1)
    assert login == "pas"
    assert bcrypt.checkpw(b"neuespasswort", digest.encode("ascii"))


def test_einstellungen_speichern_zeigt_bestaetigung(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    client = TestClient(app)
    client.post("/einstellungen", data={"archivio_db_path": "", "archivio_min_mails": "2"})
    r = client.get("/einstellungen?gespeichert=1")
    assert "Gespeichert" in r.text


def test_einstellungen_speichert_firmenname(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    TestClient(app).post("/einstellungen", data={
        "archivio_db_path": "", "archivio_min_mails": "2", "export_firmenname": "Strut Architekten AG",
    })
    assert settings.get("export.firmenname") == "Strut Architekten AG"


def test_einstellungen_speichert_export_checkboxen(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    client = TestClient(app)
    # Checkboxen aktiviert (HTML-Formulare senden nur angehakte Checkboxen mit)
    client.post("/einstellungen", data={
        "archivio_db_path": "", "archivio_min_mails": "2",
        "privates_telefon_zeigen": "on", "private_email_zeigen": "on", "privatadresse_zeigen": "on",
    })
    assert settings.get("export.privates_telefon_zeigen") is True
    assert settings.get("export.private_email_zeigen") is True
    assert settings.get("export.privatadresse_zeigen") is True

    # Nicht angehakt -> muss auf False zurueckgesetzt werden (nicht einfach fehlen)
    client.post("/einstellungen", data={"archivio_db_path": "", "archivio_min_mails": "2"})
    assert settings.get("export.privates_telefon_zeigen") is False


def test_einstellungen_formular_zeigt_checkbox_status(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"export": {"privates_telefon_zeigen": True}})
    r = TestClient(app).get("/einstellungen")
    assert r.status_code == 200
    # Nur die aktivierte Checkbox soll "checked" haben
    abschnitt = r.text.split('name="privates_telefon_zeigen"')[1][:20]
    assert "checked" in abschnitt


def test_logo_upload_wird_gespeichert_und_ausgeliefert(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    client = TestClient(app)
    bild_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-png-inhalt"
    r = client.post("/einstellungen", data={"archivio_db_path": "", "archivio_min_mails": "2"},
                    files={"logo": ("mein-logo.png", bild_bytes, "image/png")}, follow_redirects=False)
    assert r.status_code == 303

    r = client.get("/einstellungen")
    assert 'src="/einstellungen/logo"' in r.text

    r = client.get("/einstellungen/logo")
    assert r.status_code == 200
    assert r.content == bild_bytes


def test_logo_upload_lehnt_unerlaubte_dateiendung_ab(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    client = TestClient(app)
    client.post("/einstellungen", data={"archivio_db_path": "", "archivio_min_mails": "2"},
                files={"logo": ("script.exe", b"nicht ein bild", "application/octet-stream")})

    r = client.get("/einstellungen/logo")
    assert r.status_code == 404


def test_logo_entfernen(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    client = TestClient(app)
    client.post("/einstellungen", data={"archivio_db_path": "", "archivio_min_mails": "2"},
                files={"logo": ("logo.png", b"echtbild", "image/png")})
    assert client.get("/einstellungen/logo").status_code == 200

    client.post("/einstellungen/logo/entfernen")
    assert client.get("/einstellungen/logo").status_code == 404
