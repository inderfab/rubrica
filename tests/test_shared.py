import json

from config import settings
from web.shared import _update_verfuegbar, importiere_kontakte_app_und_synchronisiere


def test_importiere_kontakte_app_und_synchronisiere_pusht_jeden_kontakt(tmp_db, monkeypatch):
    """Regression: importierte Kontakte muessen nach Radicale gepusht werden, sonst
    erscheinen sie nie in Apple Kontakte (nur individuelles Bearbeiten pushte bisher -
    der Bug, der beim ersten Live-Test mit dem neuen Kontakte.app-Import auffiel)."""
    import importer.contacts_app as contacts_app_modul
    import sync.radicale as radicale_modul

    def _fake_import(conn, fortschritt_callback=None):
        if fortschritt_callback:
            fortschritt_callback(1, 2)
            fortschritt_callback(2, 2)
        return {
            "gefunden": 2, "gruppen_gefunden": 0, "importiert": 2, "fehler": 0,
            "fehler_typen": {}, "ohne_uid": 0, "kontakte_gesamt": 2, "ordner_gesamt": 0,
            "kontakt_ids": [7, 9],
        }

    monkeypatch.setattr(contacts_app_modul, "importiere_aus_kontakte_app", _fake_import)
    gepushte_ids = []
    monkeypatch.setattr(radicale_modul, "push_kontakt_mit_ordnern",
                         lambda conn, kid, client=None: gepushte_ids.append(kid))

    phasen = []
    ergebnis = importiere_kontakte_app_und_synchronisiere(
        tmp_db, fortschritt_callback=lambda phase, v, g: phasen.append((phase, v, g)))

    assert gepushte_ids == [7, 9]
    assert "kontakt_ids" not in ergebnis
    assert ergebnis["importiert"] == 2
    # "lese" einmal vorab, "importiere" waehrend des Imports, "synchronisiere"
    # waehrend des Radicale-Push - damit die UI den tatsaechlichen Fortschritt
    # zeigen kann statt eines starren "Importiere..." ueber die ganze Laufzeit.
    assert phasen[0] == ("lese", 0, 0)
    assert ("importiere", 1, 2) in phasen
    assert ("synchronisiere", 1, 2) in phasen
    assert ("synchronisiere", 2, 2) in phasen


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
