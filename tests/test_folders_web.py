from fastapi.testclient import TestClient

from db import queries
from web.main import app


def test_ordner_bearbeiten_benennt_um(tmp_db):
    ordner_id = queries.get_or_create_projekt(tmp_db, "Alter Name")
    r = TestClient(app).post(f"/ordner/{ordner_id}/bearbeiten", data={"name": "Neuer Name"},
                              follow_redirects=False)
    assert r.status_code == 303
    ordner = {o["id"]: o["name"] for o in queries.list_projekte(tmp_db)}
    assert ordner[ordner_id] == "Neuer Name"


def test_ordner_bearbeiten_ignoriert_leeren_namen(tmp_db):
    ordner_id = queries.get_or_create_projekt(tmp_db, "Bleibt")
    TestClient(app).post(f"/ordner/{ordner_id}/bearbeiten", data={"name": "   "}, follow_redirects=False)
    ordner = {o["id"]: o["name"] for o in queries.list_projekte(tmp_db)}
    assert ordner[ordner_id] == "Bleibt"


def test_ordner_liste_zeigt_bearbeiten_button(tmp_db):
    queries.get_or_create_projekt(tmp_db, "Testordner")
    r = TestClient(app).get("/ordner")
    assert "Bearbeiten" in r.text
    assert "Testordner" in r.text
