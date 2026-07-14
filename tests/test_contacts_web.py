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
    assert 'class="combobox"' in r.text
    assert "297.0 Geometer" in r.text  # vordefinierte BKP-Funktion


def test_funktionen_liste_ist_geschlechtsneutral(tmp_db):
    from web.contacts import FUNKTIONEN
    assert "291 Architekt" not in FUNKTIONEN  # nur "291 Architekt/in" soll vorkommen
    assert "291 Architekt/in" in FUNKTIONEN


def test_funktionen_liste_ist_nach_bkp_klassiert(tmp_db):
    from web.contacts import FUNKTIONEN
    # Eintraege mit BKP-Nummer sind ein einzelner String "<Nummer> <Bezeichnung>" -
    # die Combobox-Suche (app.js) filtert per Teilstring, ein Treffer ist also
    # sowohl ueber die Nummer als auch ueber die Bezeichnung auffindbar.
    geometer = next(f for f in FUNKTIONEN if "Geometer" in f)
    assert geometer.startswith("297")
    assert "Geometer" in geometer


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


def test_sammel_leiste_erscheint_vor_der_tabelle_mit_ordner_button(tmp_db):
    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    queries.get_or_create_projekt(tmp_db, "Testordner")
    r = _client(tmp_db).get("/kontakte")
    assert r.status_code == 200
    sammel_pos = r.text.index('id="sammel-leiste"')
    tabelle_pos = r.text.index("<table>")
    assert sammel_pos < tabelle_pos  # Leiste steht vor der Tabelle, nicht danach
    assert "Ordner zuweisen" in r.text
    assert "Testordner" in r.text.split('data-ordner=')[1][:200]


def test_kontakte_liste_zeigt_bearbeiten_button_kein_namenslink(tmp_db):
    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    r = _client(tmp_db).get("/kontakte")
    assert "Bearbeiten" in r.text
    assert 'href="/kontakte/1/bearbeiten"' not in r.text  # Name ist kein Link mehr


def test_bearbeiten_flyover_liefert_nur_fragment(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster", "firma": "Testfirma"})
    r = _client(tmp_db).get(f"/kontakte/{kontakt_id}/bearbeiten-flyover")
    assert r.status_code == 200
    assert "Testfirma" in r.text
    assert 'value="Anna"' in r.text
    assert "<nav>" not in r.text  # kein volles Seiten-Layout, nur das Formular-Fragment


def test_bearbeiten_flyover_gibt_ordner_id_ins_formular(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    ordner_id = queries.get_or_create_projekt(tmp_db, "Testordner")
    r = _client(tmp_db).get(f"/kontakte/{kontakt_id}/bearbeiten-flyover?ordner_id={ordner_id}")
    assert f'value="{ordner_id}"' in r.text


def test_bearbeiten_speichern_bleibt_im_ordner(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    ordner_id = queries.get_or_create_projekt(tmp_db, "Testordner")
    client = _client(tmp_db)
    r = client.post(f"/kontakte/{kontakt_id}/bearbeiten", data={
        "vorname": "Anna", "nachname": "Muster", "firma": "", "rolle": "", "kategorie": "",
        "notizen": "", "zurueck_ordner_id": str(ordner_id),
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/kontakte?ordner_id={ordner_id}"


def test_bearbeiten_speichern_ohne_ordner_kontext_geht_auf_alle(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    r = _client(tmp_db).post(f"/kontakte/{kontakt_id}/bearbeiten", data={
        "vorname": "Anna", "nachname": "Muster", "firma": "", "rolle": "", "kategorie": "",
        "notizen": "", "zurueck_ordner_id": "",
    }, follow_redirects=False)
    assert r.headers["location"] == "/kontakte"


def test_loeschen_bleibt_im_ordner(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    ordner_id = queries.get_or_create_projekt(tmp_db, "Testordner")
    r = _client(tmp_db).post(f"/kontakte/{kontakt_id}/loeschen",
                              data={"zurueck_ordner_id": str(ordner_id)}, follow_redirects=False)
    assert r.headers["location"] == f"/kontakte?ordner_id={ordner_id}"


def test_bulk_bearbeiten_flyover_markiert_unterschiedliche_werte(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster", "firma": "Firma A"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel", "firma": "Firma A"})
    r = _client(tmp_db).get(f"/kontakte/bulk-bearbeiten-flyover?ids={k1}&ids={k2}")
    assert r.status_code == 200
    assert 'value="Firma A"' in r.text  # gleiche Firma -> vorausgefuellt
    assert "Unterschiedliche Werte" in r.text  # unterschiedliche Vornamen


def test_bulk_bearbeiten_speichern_wendet_ausgefuelltes_feld_auf_alle_an(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster", "firma": "Alt A"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel", "firma": "Alt B"})
    client = _client(tmp_db)
    r = client.post("/kontakte/bulk-bearbeiten", data={
        "ids": [str(k1), str(k2)],
        "vorname": "", "vorname__gemischt": "1",
        "nachname": "", "nachname__gemischt": "1",
        "firma": "Neue Firma", "firma__gemischt": "1",
        "rolle": "", "rolle__gemischt": "0",
        "kategorie": "", "kategorie__gemischt": "0",
        "notizen": "", "notizen__gemischt": "0",
        "zurueck_ordner_id": "",
    }, follow_redirects=False)
    assert r.status_code == 303

    kontakt1 = queries.get_kontakt(tmp_db, k1)
    kontakt2 = queries.get_kontakt(tmp_db, k2)
    assert kontakt1["firma"] == "Neue Firma"
    assert kontakt2["firma"] == "Neue Firma"
    assert kontakt1["vorname"] == "Anna"  # unangetastet gelassenes "gemischt"-Feld bleibt erhalten
    assert kontakt2["vorname"] == "Bob"


def test_update_kontakt_felder_laesst_kontaktdaten_arrays_unangetastet(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [{"typ": "mobil", "nummer": "079 000 00 00"}],
    })
    queries.update_kontakt_felder(tmp_db, kontakt_id, {"firma": "Neue Firma", "rolle": "Chefin"})
    kontakt = queries.get_kontakt(tmp_db, kontakt_id)
    assert kontakt["firma"] == "Neue Firma"
    assert kontakt["rolle"] == "Chefin"
    assert kontakt["telefonnummern"][0]["nummer"] == "079 000 00 00"  # unveraendert


def test_kategorie_umstellen_nur_passende_eintraege(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [
            {"typ": "Allgemein", "nummer": "052 111 11 11"},
            {"typ": "Direkt", "nummer": "052 222 22 22"},
        ],
    })
    queries.kategorie_umstellen(tmp_db, "telefon", kontakt_id, "Allgemein", "Privat")
    typen = {t["nummer"]: t["typ"] for t in queries.get_kontakt(tmp_db, kontakt_id)["telefonnummern"]}
    assert typen["052 111 11 11"] == "Privat"
    assert typen["052 222 22 22"] == "Direkt"


def test_feld_werte_uebersicht_zaehlt_kontakte_pro_wert(tmp_db):
    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "A", "kategorie": "Architekt/in"})
    queries.create_kontakt(tmp_db, {"vorname": "Bea", "nachname": "B", "kategorie": "Architekt/in"})
    queries.create_kontakt(tmp_db, {"vorname": "Chris", "nachname": "C", "kategorie": "Bauleiter/in"})
    queries.create_kontakt(tmp_db, {"vorname": "Dora", "nachname": "D", "kategorie": ""})

    werte = {w["wert"]: w["anzahl"] for w in queries.feld_werte_uebersicht(tmp_db, "kategorie")}
    assert werte == {"Architekt/in": 2, "Bauleiter/in": 1}


def test_feld_wert_umbenennen_aendert_alle_betroffenen_kontakte(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "A", "kategorie": "Architeckt/in"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bea", "nachname": "B", "kategorie": "Architeckt/in"})
    k3 = queries.create_kontakt(tmp_db, {"vorname": "Chris", "nachname": "C", "kategorie": "Bauleiter/in"})

    betroffene = queries.feld_wert_umbenennen(tmp_db, "kategorie", "Architeckt/in", "Architekt/in")

    assert set(betroffene) == {k1, k2}
    assert queries.get_kontakt(tmp_db, k1)["kategorie"] == "Architekt/in"
    assert queries.get_kontakt(tmp_db, k2)["kategorie"] == "Architekt/in"
    assert queries.get_kontakt(tmp_db, k3)["kategorie"] == "Bauleiter/in"  # unberuehrt


def test_feld_wert_umbenennen_mit_leerem_neuen_wert_entfernt_zuweisung(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "A", "rolle": "Praktikant"})
    queries.feld_wert_umbenennen(tmp_db, "rolle", "Praktikant", "")
    assert queries.get_kontakt(tmp_db, k1)["rolle"] == ""


def test_feld_wert_umbenennen_kann_zusammenfuehren(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "A", "rolle": "Chef"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bea", "nachname": "B", "rolle": "Geschaeftsleitung"})
    queries.feld_wert_umbenennen(tmp_db, "rolle", "Chef", "Geschaeftsleitung")
    assert queries.get_kontakt(tmp_db, k1)["rolle"] == "Geschaeftsleitung"
    assert queries.get_kontakt(tmp_db, k2)["rolle"] == "Geschaeftsleitung"


def test_feld_wert_umbenennen_ignoriert_unbekanntes_feld(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "A", "rolle": "Chef"})
    betroffene = queries.feld_wert_umbenennen(tmp_db, "firma", "Chef", "Andere")
    assert betroffene == []
    assert queries.get_kontakt(tmp_db, k1)["rolle"] == "Chef"


def test_funktionen_rollen_uebersicht_seite_zeigt_werte_und_anzahl(tmp_db):
    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "A", "kategorie": "Architekt/in"})
    queries.create_kontakt(tmp_db, {"vorname": "Bea", "nachname": "B", "rolle": "Chefin"})

    r = _client(tmp_db).get("/einstellungen/funktionen-rollen")
    assert r.status_code == 200
    assert "Architekt/in" in r.text
    assert "Chefin" in r.text


def test_funktionen_rollen_umbenennen_route_aendert_kontakte(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "A", "kategorie": "Architeckt/in"})
    client = _client(tmp_db)

    r = client.post("/einstellungen/funktionen-rollen/umbenennen", data={
        "feld": "kategorie", "alter_wert": "Architeckt/in", "neuer_wert": "Architekt/in",
    }, follow_redirects=False)

    assert r.status_code == 303
    assert queries.get_kontakt(tmp_db, k1)["kategorie"] == "Architekt/in"


def test_bulk_bearbeiten_speichern_laesst_gleiche_felder_unveraendert_wenn_nicht_editiert(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster", "rolle": "Chefin"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel", "rolle": "Chefin"})
    client = _client(tmp_db)
    client.post("/kontakte/bulk-bearbeiten", data={
        "ids": [str(k1), str(k2)],
        "vorname": "", "vorname__gemischt": "1",
        "nachname": "", "nachname__gemischt": "1",
        "firma": "", "firma__gemischt": "0",
        "rolle": "Chefin", "rolle__gemischt": "0",
        "kategorie": "", "kategorie__gemischt": "0",
        "notizen": "", "notizen__gemischt": "0",
        "zurueck_ordner_id": "",
    }, follow_redirects=False)
    assert queries.get_kontakt(tmp_db, k1)["rolle"] == "Chefin"
    assert queries.get_kontakt(tmp_db, k2)["rolle"] == "Chefin"


def test_bulk_kategorie_umstellen_telefon_bei_allen_ausgewaehlten(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [{"typ": "Allgemein", "nummer": "052 111 11 11"}, {"typ": "Direkt", "nummer": "052 999 99 99"}],
    })
    k2 = queries.create_kontakt(tmp_db, {
        "vorname": "Bob", "nachname": "Beispiel",
        "telefonnummern": [{"typ": "Allgemein", "nummer": "052 222 22 22"}],
    })
    _client(tmp_db).post("/kontakte/bulk-kategorie-umstellen", data={
        "ids": [str(k1), str(k2)], "zurueck_ordner_id": "",
        "feld": "telefon", "telefon_von": "Allgemein", "telefon_nach": "Privat",
    }, follow_redirects=False)

    typen_k1 = {t["nummer"]: t["typ"] for t in queries.get_kontakt(tmp_db, k1)["telefonnummern"]}
    assert typen_k1["052 111 11 11"] == "Privat"
    assert typen_k1["052 999 99 99"] == "Direkt"  # nicht betroffen, war schon "Direkt"
    typen_k2 = {t["nummer"]: t["typ"] for t in queries.get_kontakt(tmp_db, k2)["telefonnummern"]}
    assert typen_k2["052 222 22 22"] == "Privat"


def test_bulk_kategorie_umstellen_email_unabhaengig_von_telefon(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "emails": [{"typ": "Allgemein", "email": "info@firma.ch"}],
        "telefonnummern": [{"typ": "Allgemein", "nummer": "052 111 11 11"}],
    })
    _client(tmp_db).post("/kontakte/bulk-kategorie-umstellen", data={
        "ids": [str(k1)], "zurueck_ordner_id": "",
        "feld": "email", "email_von": "Allgemein", "email_nach": "Privat",
    }, follow_redirects=False)

    kontakt = queries.get_kontakt(tmp_db, k1)
    assert kontakt["emails"][0]["typ"] == "Privat"
    assert kontakt["telefonnummern"][0]["typ"] == "Allgemein"  # Telefon bleibt unangetastet


def test_bulk_kategorie_umstellen_ignoriert_ungueltiges_feld(tmp_db):
    k1 = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [{"typ": "Allgemein", "nummer": "052 111 11 11"}],
    })
    r = _client(tmp_db).post("/kontakte/bulk-kategorie-umstellen", data={
        "ids": [str(k1)], "zurueck_ordner_id": "",
        "feld": "adresse", "adresse_von": "Allgemein", "adresse_nach": "Privat",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert queries.get_kontakt(tmp_db, k1)["telefonnummern"][0]["typ"] == "Allgemein"
