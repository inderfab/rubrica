import sqlite3

from fastapi.testclient import TestClient

from config import settings
from db import queries
from web.main import app
import backup


def test_ohne_konfigurierten_pfad_tut_nichts(tmp_db, tmp_path):
    monkeypatch_leer = tmp_path / "sollte-nicht-entstehen"
    backup.sichern_falls_konfiguriert()
    assert not monkeypatch_leer.exists()


def test_schreibt_konsistenten_snapshot(tmp_db, tmp_path, monkeypatch):
    ziel = tmp_path / "nas-ordner"
    monkeypatch.setattr(settings, "_settings", {"backup": {"pfad": str(ziel)}})

    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    backup.sichern_falls_konfiguriert()

    ziel_datei = ziel / backup.DATEINAME
    assert ziel_datei.exists()

    sicherung = sqlite3.connect(str(ziel_datei))
    try:
        namen = [r[0] for r in sicherung.execute("SELECT nachname FROM kontakte")]
    finally:
        sicherung.close()
    assert namen == ["Muster"]


def test_ueberschreibt_bestehende_sicherung_statt_zu_akkumulieren(tmp_db, tmp_path, monkeypatch):
    ziel = tmp_path / "nas-ordner"
    monkeypatch.setattr(settings, "_settings", {"backup": {"pfad": str(ziel)}})

    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    backup.sichern_falls_konfiguriert()
    queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel"})
    backup.sichern_falls_konfiguriert()

    ziel_datei = ziel / backup.DATEINAME
    sicherung = sqlite3.connect(str(ziel_datei))
    try:
        anzahl = sicherung.execute("SELECT COUNT(*) FROM kontakte").fetchone()[0]
    finally:
        sicherung.close()
    assert anzahl == 2  # eine Datei, immer aktuell - keine wachsende Anzahl Snapshot-Dateien


def test_ungueltiger_pfad_wirft_keine_exception(tmp_db, tmp_path, monkeypatch):
    # Datei statt Ordner als "Pfad" - mkdir(parents=True) schlaegt fehl, darf aber
    # eine normale Kontakt-Aenderung nicht zum Absturz bringen (best-effort).
    blockierende_datei = tmp_path / "ist-eine-datei"
    blockierende_datei.write_text("x")
    monkeypatch.setattr(settings, "_settings", {"backup": {"pfad": str(blockierende_datei / "unterordner")}})

    backup.sichern_falls_konfiguriert()  # darf nicht werfen


def test_middleware_sichert_nach_erfolgreichem_post(tmp_db, tmp_path, monkeypatch):
    ziel = tmp_path / "nas-ordner"
    monkeypatch.setattr(settings, "_settings", {"backup": {"pfad": str(ziel)}})

    TestClient(app).post("/kontakte/neu", data={
        "vorname": "Anna", "nachname": "Muster", "firma": "", "rolle": "", "kategorie": "", "notizen": "",
    })

    assert (ziel / backup.DATEINAME).exists()
