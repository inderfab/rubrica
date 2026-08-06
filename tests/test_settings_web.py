import bcrypt
from fastapi.testclient import TestClient

from config import settings
from sync import htpasswd
from web.main import app


def test_einstellungen_formular_zeigt_aktuellen_wert(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": "/pfad/archivio.db", "min_mails": 3}})
    r = TestClient(app).get("/einstellungen")
    assert r.status_code == 200
    assert "/pfad/archivio.db" in r.text
    assert 'value="3"' in r.text


def test_ca_zertifikat_download_ohne_datei_ist_404(tmp_db):
    r = TestClient(app).get("/einstellungen/ca-zertifikat")
    assert r.status_code == 404


def test_ca_zertifikat_download_liefert_datei(tmp_db):
    tls_dir = settings.daten_verzeichnis() / "radicale-tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    (tls_dir / "ca-cert.pem").write_text("-----BEGIN CERTIFICATE-----\ndummy\n-----END CERTIFICATE-----\n",
                                          encoding="utf-8")

    r = TestClient(app).get("/einstellungen/ca-zertifikat")
    assert r.status_code == 200
    assert b"BEGIN CERTIFICATE" in r.content


def test_einstellungen_seite_zeigt_download_link_nur_wenn_zertifikat_vorhanden(tmp_db):
    r = TestClient(app).get("/einstellungen")
    assert "/einstellungen/ca-zertifikat" not in r.text

    tls_dir = settings.daten_verzeichnis() / "radicale-tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    (tls_dir / "ca-cert.pem").write_text("dummy", encoding="utf-8")

    r2 = TestClient(app).get("/einstellungen")
    assert "/einstellungen/ca-zertifikat" in r2.text


def test_radicale_sync_button_ohne_konfiguration_meldet_inaktiv(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": ""}})
    r = TestClient(app).post("/einstellungen/radicale-sync", follow_redirects=False)
    assert r.status_code == 303
    assert "sync=" in r.headers["location"]


def test_alle_kontakte_loeschen_entfernt_alle_kontakte_behaelt_ordner(tmp_db, monkeypatch):
    from db import queries
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": ""}})
    ordner_id = queries.get_or_create_projekt(tmp_db, "Testordner")
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel"})
    queries.set_kontakt_projekte(tmp_db, k1, [ordner_id])

    r = TestClient(app).post("/einstellungen/alle-kontakte-loeschen", follow_redirects=False)
    assert r.status_code == 303
    assert "reset=" in r.headers["location"]

    assert queries.list_kontakte(tmp_db) == []
    assert len(queries.list_projekte(tmp_db)) == 1  # Ordner bleibt erhalten

    r2 = TestClient(app).get(r.headers["location"])
    assert "2 Kontakte gelöscht" in r2.text


def test_alle_kontakte_loeschen_mit_auch_ordner_entfernt_auch_ordner(tmp_db, monkeypatch):
    from db import queries
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": ""}})
    queries.get_or_create_projekt(tmp_db, "Testordner")
    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})

    r = TestClient(app).post("/einstellungen/alle-kontakte-loeschen", data={"auch_ordner": "1"},
                              follow_redirects=False)
    assert r.status_code == 303

    assert queries.list_kontakte(tmp_db) == []
    assert queries.list_projekte(tmp_db) == []

    r2 = TestClient(app).get(r.headers["location"])
    assert "1 Kontakte und 1 Ordner gelöscht" in r2.text


def test_mail_test_ohne_konfiguration_meldet_kein_server(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"mail": {"host": ""}})
    r = TestClient(app).post("/einstellungen/mail-test", follow_redirects=False)
    assert r.status_code == 303
    assert "mail=" in r.headers["location"]

    r2 = TestClient(app).get(r.headers["location"])
    assert "Kein IMAP-Server konfiguriert" in r2.text


def test_mail_pruefen_ruft_mail_intake_auf(tmp_db, monkeypatch):
    import web.settings as settings_modul

    monkeypatch.setattr(settings_modul.mail_intake, "pruefe_mail_eingang", lambda conn: {
        "aktiv": True, "gefunden": 3, "neu": 2, "fehler": 1,
    })

    r = TestClient(app).post("/einstellungen/mail-pruefen", follow_redirects=False)
    assert r.status_code == 303
    r2 = TestClient(app).get(r.headers["location"])
    assert "2 neue" in r2.text
    assert "1 Nachrichten übersprungen" in r2.text


def test_einstellungen_speichern_schreibt_config(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/einstellungen", data={
        "archivio_signatur_db_path": "/neuer/pfad/archivio.db",
        "archivio_min_mails": "5",
        "backup_pfad": "/Volumes/NAS/Rubrica-Backup",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "gespeichert=1" in r.headers["location"]

    assert settings.get("archivio.signatur_db_path") == "/neuer/pfad/archivio.db"
    assert settings.get("archivio.min_mails") == 5
    assert settings.get("backup.pfad") == "/Volumes/NAS/Rubrica-Backup"


def test_einstellungen_formular_zeigt_radicale_werte_im_klartext(tmp_db, monkeypatch):
    # Benutzername/Adressbuch-Pfad sind fest verdrahtet (siehe sync/radicale.py) -
    # die Seite zeigt immer "rubrica", unabhaengig davon, was (noch) in config.yaml
    # steht (z.B. Reste einer alten Installation).
    from web import settings as settings_modul
    monkeypatch.setattr(settings_modul, "_hostname_local", lambda: "windows.local")
    monkeypatch.setattr(settings, "_settings", {"radicale": {
        "base_url": "https://127.0.0.1:8443", "username": "contact", "password": "geheim123",
    }})
    r = TestClient(app).get("/einstellungen")
    assert r.status_code == 200
    assert "https://127.0.0.1:8443" in r.text
    assert "/rubrica/kontakte/" in r.text
    assert "geheim123" in r.text
    assert "contact" not in r.text
    # Regression: die fuer Kontakte.app relevante Adresse (Rechnername) soll
    # sichtbar sein, nicht nur die interne Loopback-Adresse (siehe Nutzer-Feedback:
    # "die Serveradresse die intern verwendet wird interessiert ja niemanden").
    assert "windows.local" in r.text


def test_einstellungen_speichern_schreibt_radicale_config(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/einstellungen", data={
        "radicale_base_url": "https://127.0.0.1:8443",
        "radicale_password": "neuespasswort",
    }, follow_redirects=False)
    assert r.status_code == 303

    assert settings.get("radicale.base_url") == "https://127.0.0.1:8443"
    assert settings.get("radicale.password") == "neuespasswort"

    # Kernpunkt des Bugfixes: das Passwort muss auch in der htpasswd-Datei landen
    # (Server-Auth), nicht nur in config.yaml (Client-Push) - sonst schlaegt der
    # Login von Kontakte.app fehl. Der Benutzername ist dabei immer "rubrica" (fest
    # verdrahtet), unabhaengig vom macOS-Konto der jeweiligen Maschine.
    inhalt = htpasswd.htpasswd_pfad().read_text(encoding="utf-8").strip()
    login, digest = inhalt.split(":", maxsplit=1)
    assert login == "rubrica"
    assert bcrypt.checkpw(b"neuespasswort", digest.encode("ascii"))


def test_einstellungen_speichern_ignoriert_versuchte_aenderung_von_benutzername(tmp_db, monkeypatch, tmp_path):
    """radicale_username/radicale_addressbook_path werden vom Formular gar nicht
    mehr gelesen (siehe web/settings.py) - selbst ein von Hand geschicktes POST mit
    diesen Feldern darf keine Wirkung haben. Verhindert den bereits aufgetretenen
    owner_only-Mismatch-Bug strukturell, nicht nur per UI-Einschraenkung."""
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    TestClient(app).post("/einstellungen", data={
        "radicale_username": "contact",
        "radicale_addressbook_path": "/contact/kontakte/",
        "radicale_password": "neuespasswort",
    }, follow_redirects=False)

    assert settings.get("radicale.username") is None
    assert settings.get("radicale.addressbook_path") is None
    inhalt = htpasswd.htpasswd_pfad().read_text(encoding="utf-8").strip()
    login, _ = inhalt.split(":", maxsplit=1)
    assert login == "rubrica"


def test_einstellungen_speichern_zeigt_bestaetigung(tmp_db, monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    client = TestClient(app)
    client.post("/einstellungen", data={"archivio_signatur_db_path": "", "archivio_min_mails": "2"})
    r = client.get("/einstellungen?gespeichert=1")
    assert "Gespeichert" in r.text


# Logo und Export-Darstellung liegen seit 2026-08-06 auf der Export-Seite -
# die zugehoerigen Tests stehen in tests/test_export.py.


# ── Kategorien fuer Telefon/E-Mail ────────────────────────────────────────────
# Die Auswahl im Kontaktformular ist bewusst ein reines Dropdown ohne Freitext
# (Nutzer-Vorgabe, sonst entsteht wieder Wildwuchs) - neue Kategorien koennen
# deshalb nur ueber diese Seite entstehen.

def test_kategorien_seite_zeigt_liste_und_bestandswerte(tmp_db):
    from db import queries
    queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [{"typ": "Direkt", "nummer": "044 111 11 11"},
                           {"typ": "Zentrale", "nummer": "044 222 22 22"}],
    })

    r = TestClient(app).get("/einstellungen/kategorien")
    assert r.status_code == 200
    for standard in settings.TELEFON_TYPEN_STANDARD:
        assert f'value="{standard}"' in r.text
    # "Zentrale" gehoert nicht zur Auswahl, muss aber sichtbar sein, damit man den
    # Ausreisser ueberhaupt bemerkt und einsortieren kann.
    assert "Zentrale" in r.text


def test_kategorie_hinzufuegen_erscheint_im_kontaktformular(tmp_db):
    client = TestClient(app)
    client.post("/einstellungen/kategorien", data={
        "feld": "telefon", "original": ["Direkt", ""], "name": ["Direkt", "Zentrale"],
    }, follow_redirects=False)

    assert settings.telefon_typen() == ["Direkt", "Zentrale"]
    r = client.get("/kontakte/neu")
    assert '<option value="Zentrale"' in r.text


def test_kategorie_umbenennen_zieht_den_bestand_mit(tmp_db):
    from db import queries
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [{"typ": "Direkt", "nummer": "044 111 11 11"}],
    })

    TestClient(app).post("/einstellungen/kategorien", data={
        "feld": "telefon", "original": ["Direkt"], "name": ["Arbeit"],
    }, follow_redirects=False)

    assert settings.telefon_typen()[0] == "Arbeit"
    assert queries.get_kontakt(tmp_db, kontakt_id)["telefonnummern"][0]["typ"] == "Arbeit"


def test_benutzte_kategorie_wird_nicht_entfernt(tmp_db):
    """Sonst haetten die betroffenen Eintraege eine Kategorie, die es zur Auswahl
    nicht mehr gibt - und das blosse Speichern des Kontakts wuerde sie still auf
    einen anderen Wert setzen."""
    from db import queries
    queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [{"typ": "Privat", "nummer": "079 111 11 11"}],
    })

    r = TestClient(app).post("/einstellungen/kategorien", data={
        "feld": "telefon", "original": ["Direkt"], "name": ["Direkt"],
    }, follow_redirects=False)

    assert "Privat" in settings.telefon_typen()
    assert "Privat" in r.headers["location"]


def test_unbenutzte_kategorie_laesst_sich_entfernen(tmp_db):
    TestClient(app).post("/einstellungen/kategorien", data={
        "feld": "telefon", "original": ["Direkt", "Privat"], "name": ["Direkt", "Privat"],
    }, follow_redirects=False)

    assert settings.telefon_typen() == ["Direkt", "Privat"]


def test_leere_liste_faellt_auf_die_standardwerte_zurueck(tmp_db):
    """Ein leeres Dropdown wuerde beim naechsten Speichern eines Kontakts alle
    Kategorien loeschen."""
    TestClient(app).post("/einstellungen/kategorien", data={"feld": "telefon"},
                          follow_redirects=False)
    assert settings.telefon_typen() == settings.TELEFON_TYPEN_STANDARD


def test_bestandswert_laesst_sich_einer_kategorie_zuordnen(tmp_db):
    from db import queries
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "emails": [{"typ": "work", "email": "anna@beispiel.ch"}],
    })

    TestClient(app).post("/einstellungen/kategorien/umbenennen", data={
        "feld": "email", "alter_wert": "work", "neuer_wert": "Direkt",
    }, follow_redirects=False)

    assert queries.get_kontakt(tmp_db, kontakt_id)["emails"][0]["typ"] == "Direkt"
    assert "work" not in settings.email_typen()


def test_kontaktformular_behaelt_nicht_konfigurierten_bestandswert(tmp_db):
    """Regression: ein <select> ohne passende Option zeigt kommentarlos die erste
    an - Oeffnen und Speichern haette die Kategorie des Kontakts still veraendert."""
    from db import queries
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [{"typ": "Zentrale", "nummer": "044 111 11 11"}],
    })

    r = TestClient(app).get(f"/kontakte/{kontakt_id}/bearbeiten")
    assert r.status_code == 200
    assert '<option value="Zentrale" selected>' in r.text


def test_carddav_felder_haengen_am_einstellungen_formular(tmp_db):
    """Der CardDAV-Block steht ueber dem Speichern-Formular und ist per
    form="einstellungen-form" damit verbunden. Ohne diese Verknuepfung wuerde das
    Feld beim Speichern fehlen - und die Route setzt ein fehlendes Passwort auf
    leer, womit sich jede Station stillschweigend nicht mehr anmelden koennte."""
    r = TestClient(app).get("/einstellungen")
    assert r.status_code == 200
    for feld in ("radicale_password", "radicale_base_url"):
        block = r.text.split(f'name="{feld}"')[0].rsplit("<input", 1)[1] + \
                r.text.split(f'name="{feld}"')[1].split(">")[0]
        assert 'form="einstellungen-form"' in block, feld


def test_einstellungen_speichern_laesst_export_werte_unberuehrt(tmp_db, monkeypatch, tmp_path):
    """Gegenstueck zum Test auf der Export-Seite: die Export-Felder stehen nicht
    mehr in diesem Formular und duerfen von hier aus nicht geleert werden."""
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})
    settings.save({"export": {"firmenname": "Muster AG", "privates_telefon_zeigen": True}})

    TestClient(app).post("/einstellungen", data={"archivio_signatur_db_path": "", "archivio_min_mails": "2"})

    assert settings.get("export.firmenname") == "Muster AG"
    assert settings.get("export.privates_telefon_zeigen") is True
