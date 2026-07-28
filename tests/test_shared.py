import json

from config import settings
from web.shared import _update_verfuegbar


def test_update_verfuegbar_ohne_datei_ist_leer(tmp_db):
    assert _update_verfuegbar() == ""


def test_update_verfuegbar_zeigt_neuere_version(tmp_db, monkeypatch):
    monkeypatch.setattr("web.shared.APP_VERSION", "1.0.0")
    pfad = settings.daten_verzeichnis() / "update_state.json"
    pfad.write_text(json.dumps({"gemeldete_version": "1.2.0"}), encoding="utf-8")
    assert _update_verfuegbar() == "1.2.0"


def test_update_verfuegbar_versteckt_bereits_installierte_version(tmp_db, monkeypatch):
    monkeypatch.setattr("web.shared.APP_VERSION", "1.2.0")
    pfad = settings.daten_verzeichnis() / "update_state.json"
    pfad.write_text(json.dumps({"gemeldete_version": "1.2.0"}), encoding="utf-8")
    assert _update_verfuegbar() == ""


def test_update_verfuegbar_bei_kaputter_datei_ist_leer(tmp_db):
    pfad = settings.daten_verzeichnis() / "update_state.json"
    pfad.write_text("kein json", encoding="utf-8")
    assert _update_verfuegbar() == ""
