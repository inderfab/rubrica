import sqlite3

import pytest
from fastapi.testclient import TestClient

from config import settings
from db import queries
from web.main import app


@pytest.fixture
def archivio_db(tmp_path):
    pfad = tmp_path / "archivio-test.db"
    conn = sqlite3.connect(pfad)
    conn.executescript("""
        CREATE TABLE signatur_quelle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            absender TEXT, absender_email TEXT, empfaenger TEXT, cc TEXT,
            postfach TEXT, projekt TEXT, betreff TEXT, text TEXT, datum TEXT,
            status TEXT NOT NULL DEFAULT 'pending', status_updated_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
    """)
    sig = "Anna Beispiel\nBeispiel AG\nT 044 123 45 67\nanna@beispiel.ch"
    for i, datum in enumerate(["2026-01-01", "2026-01-05"], start=1):
        conn.execute(
            "INSERT INTO signatur_quelle (message_id, absender_email, postfach, projekt, text, datum) "
            "VALUES (?, 'anna@beispiel.ch', '200_projekt', '200 Projekt', ?, ?)",
            (f"m{i}", sig, datum),
        )
    conn.commit()
    conn.close()
    return str(pfad)


def test_vorschau_ohne_konfiguration_zeigt_hinweis(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": ""}})
    r = TestClient(app).get("/archivio-import")
    assert r.status_code == 200
    assert "Keine Archivio-Signatur-Datenbank konfiguriert" in r.text


def test_nav_zeigt_archivio_import_nur_wenn_konfiguriert(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": ""}})
    r = TestClient(app).get("/review")
    assert "/archivio-import" not in r.text

    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": "/pfad/existiert/nicht.db"}})
    r_nicht_existent = TestClient(app).get("/review")
    assert "/archivio-import" not in r_nicht_existent.text

    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db}})
    r2 = TestClient(app).get("/review")
    assert "/archivio-import" in r2.text


def test_vorschau_zeigt_kandidat_ohne_zu_schreiben(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).get("/archivio-import")
    assert r.status_code == 200
    assert "Beispiel AG" in r.text
    assert len(queries.list_vorschlaege(tmp_db, status="offen")) == 0


def test_uebernehmen_schreibt_in_review_queue(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).post("/archivio-import/uebernehmen", follow_redirects=False)
    assert r.status_code == 303
    vorschlaege = queries.list_vorschlaege(tmp_db, status="offen")
    assert len(vorschlaege) == 1
    assert vorschlaege[0]["quelle"] == "archivio"
    assert vorschlaege[0]["rohdaten"]["firma"] == "Beispiel AG"


def test_uebernehmen_markiert_mails_als_uebernommen(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    TestClient(app).post("/archivio-import/uebernehmen", follow_redirects=False)

    conn = sqlite3.connect(archivio_db)
    status = {r[0] for r in conn.execute("SELECT status FROM signatur_quelle WHERE absender_email = 'anna@beispiel.ch'")}
    conn.close()
    assert status == {"uebernommen"}


def test_uebernehmen_erzeugt_keine_dubletten_bei_zweitem_lauf(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    client = TestClient(app)
    client.post("/archivio-import/uebernehmen", follow_redirects=False)
    client.post("/archivio-import/uebernehmen", follow_redirects=False)
    assert len(queries.list_vorschlaege(tmp_db, status="offen")) == 1


def test_einzeln_uebernehmen_erzeugt_nur_diesen_vorschlag(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).post("/archivio-import/uebernehmen-einzeln",
                              data={"email": "anna@beispiel.ch"}, follow_redirects=False)
    assert r.status_code == 303
    vorschlaege = queries.list_vorschlaege(tmp_db, status="offen")
    assert len(vorschlaege) == 1
    assert vorschlaege[0]["rohdaten"]["emails"][0]["email"] == "anna@beispiel.ch"


def test_ablehnen_verhindert_erneutes_erscheinen(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    client = TestClient(app)
    r = client.post("/archivio-import/ablehnen", data={"email": "anna@beispiel.ch"}, follow_redirects=False)
    assert r.status_code == 303

    # abgelehnter Vorschlag existiert (Status abgelehnt), taucht aber in der
    # offenen Review-Queue nicht auf
    assert len(queries.list_vorschlaege(tmp_db, status="offen")) == 0
    assert len(queries.list_vorschlaege(tmp_db, status="abgelehnt")) == 1

    # und erscheint bei einem erneuten Scan nicht wieder als Kandidat
    r2 = client.get("/archivio-import")
    assert "anna@beispiel.ch" not in r2.text
    assert "0</strong> Vorschlag" in r2.text


def test_ablehnen_markiert_mails_in_archivio_db_als_abgelehnt(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    TestClient(app).post("/archivio-import/ablehnen", data={"email": "anna@beispiel.ch"}, follow_redirects=False)

    conn = sqlite3.connect(archivio_db)
    status = {r[0] for r in conn.execute("SELECT status FROM signatur_quelle WHERE absender_email = 'anna@beispiel.ch'")}
    conn.close()
    assert status == {"abgelehnt"}


def test_postfach_zuordnen_speichert_und_wirkt_auf_kandidaten(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    ordner_id = queries.get_or_create_projekt(tmp_db, "Projekt 200")

    r = TestClient(app).post("/archivio-import/postfach-zuordnen", data={
        "postfach": "200_projekt", "projekt_id": str(ordner_id),
    }, follow_redirects=False)
    assert r.status_code == 303

    zuordnungen = queries.postfach_zuordnungen(tmp_db)
    assert zuordnungen["200_projekt"]["name"] == "Projekt 200"

    r2 = TestClient(app).get("/archivio-import")
    assert "Projekt 200" in r2.text


def test_postfach_filter_auf_seite_zeigt_ausgewaehltes_postfach(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).get("/archivio-import", params={"postfaecher": ["200_projekt"]})
    assert r.status_code == 200
    assert "Beispiel AG" in r.text


def test_bearbeiten_flyover_zeigt_vorausgefuelltes_formular(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).get("/archivio-import/bearbeiten-flyover", params={"email": "anna@beispiel.ch"})
    assert r.status_code == 200
    assert 'value="Anna"' in r.text
    assert 'value="Beispiel AG"' in r.text


def test_bearbeiten_flyover_unbekannte_email_ist_404(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).get("/archivio-import/bearbeiten-flyover", params={"email": "unbekannt@nirgends.ch"})
    assert r.status_code == 404


def test_uebernehmen_bearbeitet_verwendet_korrigierte_werte(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"signatur_db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).post("/archivio-import/uebernehmen-bearbeitet", data={
        "absender_email": "anna@beispiel.ch",
        "vorname": "Hanna",  # vom Nutzer korrigiert (statt "Anna")
        "nachname": "Beispiel",
        "firma": "Beispiel AG",
        "rolle": "",
        "telefon_typ": "Direkt", "telefon_nummer": "044 123 45 67",
        "email_typ": "Direkt", "email_email": "anna@beispiel.ch",
    }, follow_redirects=False)
    assert r.status_code == 303

    vorschlaege = queries.list_vorschlaege(tmp_db, status="offen")
    assert len(vorschlaege) == 1
    assert vorschlaege[0]["rohdaten"]["vorname"] == "Hanna"

    conn = sqlite3.connect(archivio_db)
    status = {r[0] for r in conn.execute("SELECT status FROM signatur_quelle WHERE absender_email = 'anna@beispiel.ch'")}
    conn.close()
    assert status == {"uebernommen"}
