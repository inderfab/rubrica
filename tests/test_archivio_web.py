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
        CREATE TABLE documents (id INTEGER PRIMARY KEY, source_type TEXT);
        CREATE TABLE document_content (document_id INTEGER, content TEXT);
        CREATE TABLE mails (document_id INTEGER, sender TEXT, date TEXT);
    """)
    sig = "Anna Beispiel\nBeispiel AG\nT 044 123 45 67\nanna@beispiel.ch"
    for i, datum in enumerate(["2026-01-01", "2026-01-05"], start=1):
        conn.execute("INSERT INTO documents (id, source_type) VALUES (?, 'email')", (i,))
        conn.execute("INSERT INTO document_content (document_id, content) VALUES (?, ?)", (i, sig))
        conn.execute("INSERT INTO mails (document_id, sender, date) VALUES (?, 'anna@beispiel.ch', ?)", (i, datum))
    conn.commit()
    conn.close()
    return str(pfad)


def test_vorschau_ohne_konfiguration_zeigt_hinweis(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": ""}})
    r = TestClient(app).get("/archivio-import")
    assert r.status_code == 200
    assert "Keine Archivio-Datenbank konfiguriert" in r.text


def test_nav_zeigt_archivio_import_nur_wenn_konfiguriert(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": ""}})
    r = TestClient(app).get("/review")
    assert "/archivio-import" not in r.text

    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": "/pfad/existiert/nicht.db"}})
    r_nicht_existent = TestClient(app).get("/review")
    assert "/archivio-import" not in r_nicht_existent.text

    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": archivio_db}})
    r2 = TestClient(app).get("/review")
    assert "/archivio-import" in r2.text


def test_vorschau_zeigt_kandidat_ohne_zu_schreiben(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).get("/archivio-import")
    assert r.status_code == 200
    assert "Beispiel AG" in r.text
    assert len(queries.list_vorschlaege(tmp_db, status="offen")) == 0


def test_uebernehmen_schreibt_in_review_queue(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).post("/archivio-import/uebernehmen", follow_redirects=False)
    assert r.status_code == 303
    vorschlaege = queries.list_vorschlaege(tmp_db, status="offen")
    assert len(vorschlaege) == 1
    assert vorschlaege[0]["quelle"] == "archivio"
    assert vorschlaege[0]["rohdaten"]["firma"] == "Beispiel AG"


def test_uebernehmen_erzeugt_keine_dubletten_bei_zweitem_lauf(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": archivio_db, "min_mails": 2}})
    client = TestClient(app)
    client.post("/archivio-import/uebernehmen", follow_redirects=False)
    client.post("/archivio-import/uebernehmen", follow_redirects=False)
    assert len(queries.list_vorschlaege(tmp_db, status="offen")) == 1


def test_einzeln_uebernehmen_erzeugt_nur_diesen_vorschlag(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": archivio_db, "min_mails": 2}})
    r = TestClient(app).post("/archivio-import/uebernehmen-einzeln",
                              data={"email": "anna@beispiel.ch"}, follow_redirects=False)
    assert r.status_code == 303
    vorschlaege = queries.list_vorschlaege(tmp_db, status="offen")
    assert len(vorschlaege) == 1
    assert vorschlaege[0]["rohdaten"]["emails"][0]["email"] == "anna@beispiel.ch"


def test_ablehnen_verhindert_erneutes_erscheinen(tmp_db, archivio_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"archivio": {"db_path": archivio_db, "min_mails": 2}})
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
