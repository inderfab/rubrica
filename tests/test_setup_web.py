import sqlite3

from fastapi.testclient import TestClient

from config import settings
from db import queries
from sync import radicale
from web import import_status, setup as setup_modul
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


def test_setup_blockierung_ist_lesbares_utf8_ohne_mojibake(tmp_db):
    # Regression: Response() ohne media_type liess den Browser die UTF-8-Bytes als
    # Latin-1 interpretieren ("möglich" -> "mÃ¶glich"). content-type muss den
    # Zeichensatz jetzt explizit deklarieren.
    r = TestClient(app).get("/setup/1")
    assert r.status_code == 403
    assert "charset=utf-8" in r.headers["content-type"].lower()
    assert "möglich" in r.text
    assert "Ã¶" not in r.text


def test_setup_erlaubt_zugriff_ueber_eigene_lan_ip(tmp_db, monkeypatch):
    # Regression: der Bonjour-Hostname (z.B. "windows.local") loest auf die
    # tatsaechliche LAN-IP auf, nicht auf 127.0.0.1 - auch direkt am Server-Rechner
    # selbst aufgerufen sah request.client.host dadurch wie eine fremde IP aus.
    from web import shared as shared_modul
    monkeypatch.setattr(shared_modul, "_eigene_ip_adressen", lambda: {"127.0.0.1", "::1", "192.168.1.50"})

    class _FakeClient:
        host = "192.168.1.50"

    class _FakeRequest:
        client = _FakeClient()

    assert shared_modul._ist_lokale_maschine(_FakeRequest()) is True


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


def test_setup_schritt3_zeigt_carddav_zugangsdaten(tmp_db, monkeypatch):
    _lokal_bypass(monkeypatch)
    monkeypatch.setattr(settings, "_settings", {"radicale": {"password": "geheim123"}})

    r = TestClient(app).get("/setup/3")
    assert r.status_code == 200
    assert radicale.RADICALE_BENUTZER in r.text
    assert "geheim123" in r.text


def test_setup_seiten_laden_app_js_fuer_kontakte_app_import_knopf(tmp_db, monkeypatch):
    # Regression: setup_base.html band app.js nie ein - der "Aus Kontakte.app
    # importieren"-Knopf auf Schritt 4 rief rubricaKontakteAppImportStarten() auf,
    # die dadurch schlicht nicht existierte (ReferenceError in der Konsole, fuer den
    # Nutzer aber "nichts passiert" beim Klicken - kein sichtbarer Fehler).
    _lokal_bypass(monkeypatch)
    r = TestClient(app).get("/setup/4")
    assert r.status_code == 200
    assert '/static/app.js' in r.text
    assert "rubricaKontakteAppImportStarten" in r.text


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


def test_carddav_test_legt_adressbuch_bei_404_an_und_meldet_erfolg(tmp_db, monkeypatch):
    """Bei einer frischen Installation wurde noch nie etwas nach Radicale gepusht -
    die Adressbuch-Collection existiert dann noch nicht, ein PROPFIND liefert 404.
    Der Test soll das nicht faelschlich als Fehlschlag melden, sondern die Collection
    per MKCOL anlegen und erneut pruefen (siehe scripts/build-pkg.sh-unabhaengiger
    Bugfix in web/setup.py)."""
    _lokal_bypass(monkeypatch)

    aufrufe = []

    class _FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

    class _FakeClient:
        def request(self, methode, pfad, headers=None, content=None):
            aufrufe.append(methode)
            if methode == "PROPFIND" and aufrufe.count("PROPFIND") == 1:
                return _FakeResponse(404)
            if methode == "MKCOL":
                return _FakeResponse(201)
            return _FakeResponse(207)

        def close(self):
            pass

    monkeypatch.setattr(radicale, "_client", lambda: _FakeClient())

    r = TestClient(app).post("/setup/carddav-test")
    assert r.status_code == 200
    daten = r.json()
    assert daten["ok"] is True
    assert aufrufe == ["PROPFIND", "MKCOL", "PROPFIND"]


def test_import_contacts_app_startet_hintergrund_job(tmp_db, monkeypatch):
    _lokal_bypass(monkeypatch)
    monkeypatch.setattr(import_status, "starten", lambda: True)

    r = TestClient(app).post("/setup/import-contacts-app")
    assert r.status_code == 200
    assert r.json() == {"gestartet": True}


def test_import_contacts_app_status_meldet_laufenden_fortschritt(tmp_db, monkeypatch):
    _lokal_bypass(monkeypatch)
    monkeypatch.setattr(import_status, "status", lambda: {
        "laeuft": True, "phase": "importiere", "verarbeitet": 5, "gesamt": 10,
        "fertig": False, "ergebnis": None, "fehler_meldung": None,
    })

    r = TestClient(app).get("/setup/import-contacts-app/status")
    assert r.status_code == 200
    daten = r.json()
    assert daten["laeuft"] is True
    assert daten["verarbeitet"] == 5
    assert daten["gesamt"] == 10


def test_import_contacts_app_status_meldet_fehler(tmp_db, monkeypatch):
    _lokal_bypass(monkeypatch)
    monkeypatch.setattr(import_status, "status", lambda: {
        "laeuft": False, "phase": "", "verarbeitet": 0, "gesamt": 0,
        "fertig": True, "ergebnis": None, "fehler_meldung": "RuntimeError: Zugriff auf Kontakte verweigert",
    })

    r = TestClient(app).get("/setup/import-contacts-app/status")
    assert r.status_code == 200
    daten = r.json()
    assert daten["fertig"] is True
    assert "Zugriff auf Kontakte verweigert" in daten["fehler_meldung"]


def test_setup_schritt5_speichert_archivio_und_eigene_domains(tmp_db, monkeypatch, tmp_path):
    _lokal_bypass(monkeypatch)
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/setup/5", data={
        "archivio_signatur_db_path": "/pfad/existiert/nicht.db", "archivio_min_mails": "3",
        "archivio_eigene_domains": "@Muster.ch, Andere.CH",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/setup/5?gespeichert=1"
    assert settings.get("archivio.signatur_db_path") == "/pfad/existiert/nicht.db"
    assert settings.get("archivio.min_mails") == 3
    assert settings.get("archivio.eigene_domains") == ["muster.ch", "andere.ch"]

    r2 = TestClient(app).get("/setup/5?gespeichert=1")
    assert "Keine Datei" in r2.text


def test_setup_schritt5_zeigt_anzahl_bei_vorhandener_datei(tmp_db, monkeypatch, tmp_path):
    _lokal_bypass(monkeypatch)
    signatur_db = tmp_path / "archivio.db"
    conn = sqlite3.connect(signatur_db)
    conn.execute("CREATE TABLE signatur_quelle (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO signatur_quelle DEFAULT VALUES")
    conn.execute("INSERT INTO signatur_quelle DEFAULT VALUES")
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": str(signatur_db)}})

    r = TestClient(app).get("/setup/5")
    assert r.status_code == 200
    assert "2 Einträge" in r.text


def test_setup_schritt6_speichert_mail_konfiguration_und_leitet_weiter(tmp_db, monkeypatch, tmp_path):
    _lokal_bypass(monkeypatch)
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})

    r = TestClient(app).post("/setup/6", data={
        "mail_host": "imap.beispiel.ch", "mail_port": "993",
        "mail_username": "rubrica@beispiel.ch", "mail_password": "geheim",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/setup/7"
    assert settings.get("mail.host") == "imap.beispiel.ch"
    assert settings.get("mail.username") == "rubrica@beispiel.ch"


def test_setup_schritt6_zeigt_gespeicherte_werte(tmp_db, monkeypatch):
    _lokal_bypass(monkeypatch)
    monkeypatch.setattr(settings, "_settings", {"mail": {"host": "imap.beispiel.ch", "username": "rubrica@beispiel.ch"}})

    r = TestClient(app).get("/setup/6")
    assert r.status_code == 200
    assert "imap.beispiel.ch" in r.text
    assert "rubrica@beispiel.ch" in r.text


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
