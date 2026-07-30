from fastapi.testclient import TestClient

from db import queries
from web.main import app


def _client():
    return TestClient(app)


def test_seite_zeigt_nur_offene_mail_vorschlaege(tmp_db):
    queries.create_vorschlag(tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []},
                              quelle="mail")
    queries.create_vorschlag(tmp_db, {"vorname": "Bruno", "nachname": "Beispiel", "telefonnummern": [], "emails": []},
                              quelle="import")

    r = _client().get("/mail-vorschlaege")
    assert r.status_code == 200
    assert "Anna" in r.text
    assert "Bruno" not in r.text


def test_uebernehmen_legt_kontakt_an_und_schliesst_vorschlag(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )

    r = _client().post(f"/mail-vorschlaege/{vorschlag_id}/uebernehmen", follow_redirects=False)
    assert r.status_code == 303

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert kontakte[0]["nachname"] == "Muster"
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []


def test_ablehnen_legt_keinen_kontakt_an(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )

    r = _client().post(f"/mail-vorschlaege/{vorschlag_id}/ablehnen", follow_redirects=False)
    assert r.status_code == 303

    assert queries.list_kontakte(tmp_db) == []
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []
    assert queries.get_vorschlag(tmp_db, vorschlag_id)["status"] == "abgelehnt"


def test_bearbeiten_flyover_zeigt_formular_mit_vorbefuellten_werten(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().get(f"/mail-vorschlaege/{vorschlag_id}/bearbeiten-flyover")
    assert r.status_code == 200
    assert 'value="Anna"' in r.text
    assert 'value="Muster"' in r.text


def test_bearbeiten_flyover_unbekannter_vorschlag_ist_404(tmp_db):
    r = _client().get("/mail-vorschlaege/999999/bearbeiten-flyover")
    assert r.status_code == 404


def test_uebernehmen_bearbeitet_speichert_korrigierte_werte(tmp_db):
    projekt_id = queries.get_or_create_projekt(tmp_db, "Testprojekt")
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().post(f"/mail-vorschlaege/{vorschlag_id}/uebernehmen-bearbeitet", data={
        "vorname": "Anna", "nachname": "Korrigiert", "firma": "", "kategorie": "Geologe", "rolle": "",
        "telefon_typ": "Direkt", "telefon_nummer": "079 111 22 33",
        "email_typ": "Direkt", "email_adresse": "anna@beispiel.ch",
        "adresse_typ": "arbeit", "adresse_strasse": "Musterstrasse 1", "adresse_plz": "8000", "adresse_ort": "Zürich",
        "adresse_region": "", "adresse_land": "", "ordner_ids": str(projekt_id),
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/mail-vorschlaege"

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert kontakte[0]["nachname"] == "Korrigiert"
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []


def test_moeglicher_duplikat_zeigt_bestaetigungs_abfrage(tmp_db):
    # Regression: Nutzer-Feedback - beim Uebernehmen eines Mail-Vorschlags mit
    # bereits bekanntem Namen (aber anderer Mailadresse) kam keine Rueckfrage, im
    # Gegensatz zur manuellen Kontakt-Neuanlage. finde_match() erkennt den
    # Duplikat-Kandidaten selbst schon korrekt (siehe kontakt_id auf dem Vorschlag) -
    # es fehlte nur die sichtbare Warnung + Bestaetigung vor dem Zusammenfuehren.
    bestehender_id = queries.create_kontakt(tmp_db, {"vorname": "Bruno", "nachname": "Beispiel"})
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Bruno", "nachname": "Beispiel", "telefonnummern": [],
                 "emails": [{"typ": "Direkt", "email": "neu@beispiel.ch"}]},
        kontakt_id=bestehender_id, quelle="mail",
    )

    r = _client().get("/mail-vorschlaege")
    assert r.status_code == 200
    assert "Möglicher Duplikat" in r.text
    assert "confirm(" in r.text
    assert f"/mail-vorschlaege/{vorschlag_id}/uebernehmen" in r.text
    assert f"/kontakte/{bestehender_id}/bearbeiten" in r.text


def test_ohne_duplikat_keine_bestaetigungs_abfrage(tmp_db):
    queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().get("/mail-vorschlaege")
    assert r.status_code == 200
    assert "Möglicher Duplikat" not in r.text


def test_jetzt_pruefen_route_leitet_mit_meldung_um(tmp_db, monkeypatch):
    import mail_intake
    monkeypatch.setattr(mail_intake, "pruefe_und_beschreibe", lambda conn: "3 Nachrichten geprüft, 1 neue Kontaktvorschläge angelegt.")

    r = _client().post("/mail-vorschlaege/pruefen", follow_redirects=False)
    assert r.status_code == 303
    assert "meldung=" in r.headers["location"]

    r2 = _client().get(r.headers["location"])
    assert "1 neue Kontaktvorschläge" in r2.text
