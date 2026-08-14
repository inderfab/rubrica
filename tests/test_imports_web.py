from fastapi.testclient import TestClient

from web import import_status, imports as imports_modul
from web.main import app


def test_import_form_zeigt_knopf_nur_lokal(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: True)
    r = TestClient(app).get("/import")
    assert 'id="import-kontakte-app-knopf"' in r.text


def test_import_form_versteckt_knopf_ueber_lan(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: False)
    r = TestClient(app).get("/import")
    assert 'id="import-kontakte-app-knopf"' not in r.text


def test_import_kontakte_app_blockiert_nicht_lokale_anfragen(tmp_db):
    # TestClient simuliert Host "testclient", kein echter localhost-Request.
    r = TestClient(app).post("/import/kontakte-app")
    assert r.status_code == 200
    assert r.json()["gestartet"] is False


def test_import_kontakte_app_startet_hintergrund_job(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: True)
    monkeypatch.setattr(import_status, "starten", lambda: True)

    r = TestClient(app).post("/import/kontakte-app")
    assert r.status_code == 200
    assert r.json() == {"gestartet": True}


def test_import_kontakte_app_status_meldet_fortschritt(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: True)
    monkeypatch.setattr(import_status, "status", lambda: {
        "laeuft": True, "phase": "synchronisiere", "verarbeitet": 2, "gesamt": 2,
        "fertig": False, "ergebnis": None, "fehler_meldung": None,
    })

    r = TestClient(app).get("/import/kontakte-app/status")
    assert r.status_code == 200
    daten = r.json()
    assert daten["laeuft"] is True
    assert daten["phase"] == "synchronisiere"


def test_import_kontakte_app_status_ueber_lan_meldet_nicht_laufend(tmp_db, monkeypatch):
    monkeypatch.setattr(imports_modul, "_ist_lokal", lambda request: False)
    r = TestClient(app).get("/import/kontakte-app/status")
    assert r.status_code == 200
    assert r.json()["laeuft"] is False


def test_zusammengefuehrte_duplikate_seite_zeigt_eingehende_und_bestehende_daten(tmp_db):
    from db import queries
    bestehender_id = queries.create_kontakt(tmp_db, {
        "vorname": "Peter", "nachname": "Kunz", "emails": [{"typ": "Direkt", "email": "peter@beispiel.ch"}],
    })
    queries.create_vorschlag(
        tmp_db, {"vorname": "Peter", "nachname": "Kunz", "emails": [{"typ": "Direkt", "email": "peter@beispiel.ch"}],
                 "telefonnummern": []},
        kontakt_id=bestehender_id, quelle="import",
    )
    queries.set_vorschlag_status(tmp_db, 1, "bestaetigt")

    r = TestClient(app).get("/import/zusammengefuehrte-duplikate")
    assert r.status_code == 200
    assert "Peter Kunz" in r.text
    assert f"/kontakte/{bestehender_id}/bearbeiten" in r.text


def test_zusammengefuehrte_duplikate_seite_ohne_ergebnisse(tmp_db):
    r = TestClient(app).get("/import/zusammengefuehrte-duplikate")
    assert r.status_code == 200
    assert "Keine Zusammenführungen gefunden" in r.text


def _vcf(vorname, nachname, email, uid="X-1"):
    return (f"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\n"
            f"N:{nachname};{vorname};;;\r\nFN:{vorname} {nachname}\r\n"
            f"EMAIL;TYPE=INTERNET:{email}\r\nEND:VCARD\r\n")


def test_import_meldet_was_neu_ist_und_was_zusammengefuehrt_wurde(tmp_db):
    """Nutzer-Meldung: "es lädt und springt dann zu den kontakten. die kontakte sind
    aber dort nicht ersichtlich". Der Import leitete stumm weiter — wer nicht sieht,
    dass eine Karte in einen bestehenden Kontakt gewandert ist, sucht sie
    vergeblich in der Liste."""
    from db import queries
    queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "emails": [{"typ": "Direkt", "email": "gemeinsam@beispiel.ch"}]})

    r = TestClient(app).post("/import", files=[
        ("dateien", ("a.vcf", _vcf("Bruno", "Beispiel", "gemeinsam@beispiel.ch", "U1"), "text/vcard")),
        ("dateien", ("b.vcf", _vcf("Carla", "Neu", "carla@beispiel.ch", "U2"), "text/vcard")),
    ])

    assert r.status_code == 200
    assert "1 neu angelegt" in r.text.replace("</strong>", "").replace("<strong style=\"color:#1a7f37\">", "")
    assert "Zusammengeführt" in r.text
    assert "Anna Muster" in r.text  # dorthin ist Bruno gewandert
    assert "Carla Neu" in r.text


def test_import_kann_das_zusammenfuehren_abschalten(tmp_db):
    """Fuer das Wiederherstellen verlorener Kontakte: deren E-Mail steht nach einer
    Fehlzuordnung beim falschen Menschen, und genau darüber würde der Import sie
    sofort wieder dorthin schieben."""
    from db import queries
    queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "emails": [{"typ": "Direkt", "email": "gemeinsam@beispiel.ch"}]})

    TestClient(app).post("/import", data={"nie_zusammenfuehren": "on"}, files=[
        ("dateien", ("a.vcf", _vcf("Bruno", "Beispiel", "gemeinsam@beispiel.ch", "U1"), "text/vcard")),
    ])

    namen = {f"{k['vorname']} {k['nachname']}" for k in queries.list_kontakte(tmp_db)}
    assert namen == {"Anna Muster", "Bruno Beispiel"}
