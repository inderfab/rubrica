"""Smoke-Tests fuer die Kontakt-Neuanlage inkl. Signatur-Parsen (Web-Ebene)."""
from fastapi.testclient import TestClient

from db import queries
from web.main import app


def _client(tmp_db):
    return TestClient(app)


def test_neu_formular_erreichbar(tmp_db):
    r = _client(tmp_db).get("/kontakte/neu")
    assert r.status_code == 200
    assert "Neuer Kontakt" in r.text
    assert 'id="funktion-liste"' in r.text
    assert "Bauingenieur/Statik" in r.text  # vordefinierte Funktion im datalist


def test_signatur_parsen_fragment(tmp_db):
    sig = "Anna Muster\nMuster AG\n079 123 45 67\nanna@muster.ch"
    r = _client(tmp_db).post("/kontakte/signatur-parsen", data={"signatur": sig})
    assert r.status_code == 200
    assert 'value="Anna"' in r.text
    assert 'value="Muster AG"' in r.text
    assert "anna@muster.ch" in r.text


def test_kontakt_anlegen_speichert_und_leitet_um(tmp_db):
    projekt_id = queries.get_or_create_projekt(tmp_db, "Testprojekt")
    client = _client(tmp_db)
    r = client.post("/kontakte/neu", data={
        "vorname": "Bob", "nachname": "Beispiel", "firma": "Beispiel GmbH",
        "kategorie": "Geologe", "rolle": "",
        "telefon_typ": "mobil", "telefon_nummer": "079 111 22 33",
        "email_typ": "arbeit", "email_adresse": "bob@beispiel.ch",
        "adresse_typ": "arbeit", "adresse_strasse": "", "adresse_plz": "", "adresse_ort": "",
        "adresse_region": "", "adresse_land": "", "url_typ": "homepage", "url_adresse": "",
        "notizen": "", "ordner_ids": str(projekt_id),
    }, follow_redirects=False)
    assert r.status_code == 303

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    k = kontakte[0]
    assert k["nachname"] == "Beispiel"
    assert k["kategorie"] == "Geologe"
    assert k["telefonnummern"][0]["nummer"] == "079 111 22 33"
    assert k["projekte"][0]["name"] == "Testprojekt"


def test_ordner_drag_drop_fuegt_hinzu_ohne_bestehende_zu_entfernen(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    ordner_a = queries.get_or_create_projekt(tmp_db, "Ordner A")
    ordner_b = queries.get_or_create_projekt(tmp_db, "Ordner B")
    queries.set_kontakt_projekte(tmp_db, kontakt_id, [ordner_a])

    r = _client(tmp_db).post(f"/kontakte/{kontakt_id}/ordner/{ordner_b}/hinzufuegen")
    assert r.status_code == 204

    projekte = {p["name"] for p in queries.get_kontakt(tmp_db, kontakt_id)["projekte"]}
    assert projekte == {"Ordner A", "Ordner B"}


def test_ordner_drag_drop_ist_idempotent(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    ordner_id = queries.get_or_create_projekt(tmp_db, "Ordner A")

    client = _client(tmp_db)
    client.post(f"/kontakte/{kontakt_id}/ordner/{ordner_id}/hinzufuegen")
    r = client.post(f"/kontakte/{kontakt_id}/ordner/{ordner_id}/hinzufuegen")
    assert r.status_code == 204

    projekte = queries.get_kontakt(tmp_db, kontakt_id)["projekte"]
    assert len(projekte) == 1


def test_kontakte_liste_zeigt_ordner_sidebar_mit_anzahl(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    ordner_id = queries.get_or_create_projekt(tmp_db, "Testordner")
    queries.set_kontakt_projekte(tmp_db, kontakt_id, [ordner_id])

    r = _client(tmp_db).get("/kontakte")
    assert r.status_code == 200
    assert "Testordner" in r.text
    assert "ordner-sidebar" in r.text
