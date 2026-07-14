from fastapi.testclient import TestClient

from db import queries
from web.main import app


def client():
    return TestClient(app)


def _rohdaten(vorname="Anna", nachname="Muster", firma="", notizen="", gruppen_als_ordner=None):
    return {
        "vorname": vorname, "nachname": nachname, "firma": firma, "rolle": "",
        "kategorie": "", "notizen": notizen,
        "telefonnummern": [], "emails": [], "adressen": [], "urls": [],
        "gruppen_als_ordner": gruppen_als_ordner or [],
    }


def test_review_liste_zeigt_ordner_checkliste(tmp_db):
    ordner_id = queries.get_or_create_projekt(tmp_db, "Bestandskunden")
    queries.create_vorschlag(tmp_db, _rohdaten())

    r = client().get("/review")
    assert r.status_code == 200
    assert "Bestandskunden" in r.text
    assert "ordner_ids" in r.text


def test_bestaetigen_mit_ordner_ids_weist_zusaetzlich_zu(tmp_db):
    ordner_id = queries.get_or_create_projekt(tmp_db, "Team A")
    vid = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Beat", nachname="Muster"))

    r = client().post(f"/review/{vid}/bestaetigen", data={"ordner_ids": [str(ordner_id)]},
                       follow_redirects=False)
    assert r.status_code == 303

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    kontakt = queries.get_kontakt(tmp_db, kontakte[0]["id"])
    assert {o["id"] for o in kontakt["projekte"]} == {ordner_id}


def test_bestaetigen_behaelt_automatische_gruppen_ordner_zusaetzlich(tmp_db):
    ordner_id = queries.get_or_create_projekt(tmp_db, "Team A")
    vid = queries.create_vorschlag(
        tmp_db, _rohdaten(vorname="Chris", nachname="Muster", gruppen_als_ordner=["Erkannte Gruppe"])
    )

    client().post(f"/review/{vid}/bestaetigen", data={"ordner_ids": [str(ordner_id)]},
                  follow_redirects=False)

    kontakte = queries.list_kontakte(tmp_db)
    kontakt = queries.get_kontakt(tmp_db, kontakte[0]["id"])
    namen = {o["name"] for o in kontakt["projekte"]}
    assert namen == {"Team A", "Erkannte Gruppe"}


def test_bulk_bestaetigen_ohne_ids_bestaetigt_alle_offenen(tmp_db):
    v1 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Dana"))
    v2 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Elio"))

    r = client().post("/review/bulk-bestaetigen", follow_redirects=False)
    assert r.status_code == 303
    assert queries.list_vorschlaege(tmp_db, status="offen") == []
    assert len(queries.list_vorschlaege(tmp_db, status="bestaetigt")) == 2


def test_bulk_bestaetigen_mit_ids_bestaetigt_nur_ausgewaehlte(tmp_db):
    v1 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Fiona"))
    v2 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Gian"))

    client().post("/review/bulk-bestaetigen", data={"ids": [str(v1)]}, follow_redirects=False)

    offen = queries.list_vorschlaege(tmp_db, status="offen")
    assert len(offen) == 1
    assert offen[0]["id"] == v2


def test_bulk_ablehnen_setzt_status_fuer_ausgewaehlte(tmp_db):
    v1 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Hanna"))
    v2 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Ivo"))

    client().post("/review/bulk-ablehnen", data={"ids": [str(v1)]}, follow_redirects=False)

    offen = {v["id"] for v in queries.list_vorschlaege(tmp_db, status="offen")}
    abgelehnt = {v["id"] for v in queries.list_vorschlaege(tmp_db, status="abgelehnt")}
    assert offen == {v2}
    assert abgelehnt == {v1}


def test_bearbeiten_flyover_zeigt_alle_felder_wie_bei_kontakten(tmp_db):
    v1 = queries.create_vorschlag(tmp_db, {
        "vorname": "Anna", "nachname": "Muster", "firma": "Muster AG", "rolle": "Chefin",
        "kategorie": "291 Architekt/in", "notizen": "Testnotiz",
        "telefonnummern": [{"typ": "Direkt", "nummer": "044 123 45 67"}],
        "emails": [{"typ": "Direkt", "email": "anna@muster.ch"}],
        "adressen": [{"typ": "arbeit", "strasse": "Teststrasse 1", "plz": "8000",
                      "ort": "Zuerich", "region": "ZH", "land": "Schweiz"}],
        "urls": [{"typ": "homepage", "url": "https://muster.ch"}],
        "gruppen_als_ordner": [],
    })

    r = client().get(f"/review/{v1}/bearbeiten-flyover")
    assert r.status_code == 200
    assert 'action="/review/%d/bearbeiten-vollstaendig"' % v1 in r.text
    assert 'value="Anna"' in r.text
    assert 'value="Chefin"' in r.text
    assert 'value="044 123 45 67"' in r.text
    assert 'value="anna@muster.ch"' in r.text
    assert 'value="Teststrasse 1"' in r.text
    assert 'value="https://muster.ch"' in r.text
    assert "Testnotiz" in r.text


def test_bearbeiten_flyover_unbekannter_vorschlag_ist_404(tmp_db):
    r = client().get("/review/999999/bearbeiten-flyover")
    assert r.status_code == 404


def test_bearbeiten_flyover_checkt_ordner_aus_gruppen_als_ordner(tmp_db):
    ordner_id = queries.get_or_create_projekt(tmp_db, "Team A")
    v1 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Anna", gruppen_als_ordner=["Team A"]))

    r = client().get(f"/review/{v1}/bearbeiten-flyover")
    assert r.status_code == 200
    import re
    m = re.search(r'value="%d"[^>]*' % ordner_id, r.text)
    assert m is not None and "checked" in m.group(0)


def test_bearbeiten_vollstaendig_speichert_arrays_und_scalar_felder(tmp_db):
    v1 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Anna", nachname="Muster"))

    r = client().post(f"/review/{v1}/bearbeiten-vollstaendig", data={
        "vorname": "Hanna", "nachname": "Muster", "firma": "Neue AG", "rolle": "",
        "kategorie": "", "notizen": "",
        "telefon_typ": ["Direkt"], "telefon_nummer": ["044 999 88 77"],
        "email_typ": ["Direkt"], "email_adresse": ["hanna@neu.ch"],
        "adresse_typ": [], "adresse_strasse": [], "adresse_plz": [], "adresse_ort": [],
        "adresse_region": [], "adresse_land": [],
        "url_typ": [], "url_adresse": [],
        "ordner_ids": [],
    }, follow_redirects=False)
    assert r.status_code == 303

    rohdaten = queries.get_vorschlag(tmp_db, v1)["rohdaten"]
    assert rohdaten["vorname"] == "Hanna"
    assert rohdaten["firma"] == "Neue AG"
    assert rohdaten["telefonnummern"] == [{"typ": "Direkt", "nummer": "044 999 88 77"}]
    assert rohdaten["emails"] == [{"typ": "Direkt", "email": "hanna@neu.ch"}]


def test_bearbeiten_vollstaendig_setzt_gruppen_als_ordner_aus_checkliste(tmp_db):
    ordner_id = queries.get_or_create_projekt(tmp_db, "Team B")
    v1 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Anna"))

    client().post(f"/review/{v1}/bearbeiten-vollstaendig", data={
        "vorname": "Anna", "nachname": "", "firma": "", "rolle": "", "kategorie": "", "notizen": "",
        "ordner_ids": [str(ordner_id)],
    }, follow_redirects=False)

    rohdaten = queries.get_vorschlag(tmp_db, v1)["rohdaten"]
    assert rohdaten["gruppen_als_ordner"] == ["Team B"]


def test_bulk_bearbeiten_flyover_markiert_unterschiedliche_werte_als_gemischt(tmp_db):
    v1 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Jonas", firma="Muster AG"))
    v2 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Kim", firma="Andere AG"))

    r = client().get(f"/review/bulk-bearbeiten-flyover?ids={v1}&ids={v2}")
    assert r.status_code == 200
    assert "Unterschiedliche Werte" in r.text


def test_bulk_bearbeiten_speichern_setzt_gemeinsamen_wert_bei_allen(tmp_db):
    v1 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Jonas", firma="Muster AG"))
    v2 = queries.create_vorschlag(tmp_db, _rohdaten(vorname="Kim", firma="Andere AG"))

    client().post("/review/bulk-bearbeiten", data={
        "ids": [str(v1), str(v2)],
        "vorname": "", "vorname__gemischt": "1",
        "nachname": "", "nachname__gemischt": "0",
        "firma": "Neue AG", "firma__gemischt": "1",
        "rolle": "", "rolle__gemischt": "0",
        "kategorie": "", "kategorie__gemischt": "0",
        "notizen": "", "notizen__gemischt": "0",
    }, follow_redirects=False)

    v1_neu = queries.get_vorschlag(tmp_db, v1)
    v2_neu = queries.get_vorschlag(tmp_db, v2)
    assert v1_neu["rohdaten"]["vorname"] == "Jonas"
    assert v2_neu["rohdaten"]["vorname"] == "Kim"
    assert v1_neu["rohdaten"]["firma"] == "Neue AG"
    assert v2_neu["rohdaten"]["firma"] == "Neue AG"
