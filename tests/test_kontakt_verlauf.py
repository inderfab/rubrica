"""Verlauf/Historie fuer Kontaktaenderungen (siehe db/queries.py::update_kontakt /
protokolliere_aenderung). Nutzer-Anlass: eine in Kontakte.app korrigierte Adresse
stand nach einem Voll-Sync-Lauf wieder auf dem alten Wert, ohne dass sich das
irgendwo nachvollziehen liess (siehe v1.26.0 - der eigentliche Fehler wurde dort
behoben, dieser Verlauf ist die zusaetzliche Nachvollziehbarkeit fuer kuenftige
Faelle)."""
from db import queries


def _kontakt_mit_adresse(tmp_db):
    return queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "adressen": [
            {"typ": "Arbeit", "strasse": "Musterstrasse 1", "plz": "8000", "ort": "Zürich",
             "region": "", "land": "Schweiz"},
            {"typ": "Privat", "strasse": "Alte Gasse 3", "plz": "8400", "ort": "Winterthur",
             "region": "", "land": "Schweiz"},
        ],
    })


def test_unveraendertes_speichern_erzeugt_keinen_verlauf(tmp_db):
    kid = _kontakt_mit_adresse(tmp_db)
    kontakt = queries.get_kontakt(tmp_db, kid)
    queries.update_kontakt(tmp_db, kid, dict(kontakt))
    assert queries.kontakt_verlauf(tmp_db, kid) == []


def test_geaenderte_adresse_erzeugt_verlauf_eintrag(tmp_db):
    kid = _kontakt_mit_adresse(tmp_db)
    kontakt = queries.get_kontakt(tmp_db, kid)
    neu = dict(kontakt)
    neu["adressen"] = [
        kontakt["adressen"][0],
        {**kontakt["adressen"][1], "strasse": "Neue Gasse 8", "ort": "Hagenbuch"},
    ]
    queries.update_kontakt(tmp_db, kid, neu, quelle="kontakte_app")

    verlauf = queries.kontakt_verlauf(tmp_db, kid)
    assert len(verlauf) == 1
    assert verlauf[0]["quelle"] == "kontakte_app"
    assert len(verlauf[0]["felder"]) == 1
    eintrag = verlauf[0]["felder"][0]
    assert eintrag["feld"] == "adressen"
    assert "Alte Gasse 3" in eintrag["alt"]
    assert "Neue Gasse 8" in eintrag["neu"]


def test_funktion_wird_im_verlauf_erfasst(tmp_db):
    """Regression: kontakte_app_intake._VERGLEICHSFELDER (fuer den Kontakte.app-
    Abgleich gedacht) laesst "kategorie" (= Funktion) aus, weil eine vCard dafuer
    keine verlaessliche Entsprechung liefert. Der Verlauf braucht eine EIGENE
    Feldliste, sonst faellt ausgerechnet eines der meistgenutzten Felder heraus."""
    kid = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster", "kategorie": "Architekt/in"})
    kontakt = queries.get_kontakt(tmp_db, kid)
    neu = dict(kontakt)
    neu["kategorie"] = "Bauingenieur/in (Statik)"
    queries.update_kontakt(tmp_db, kid, neu)

    verlauf = queries.kontakt_verlauf(tmp_db, kid)
    assert len(verlauf) == 1
    assert verlauf[0]["felder"][0]["feld"] == "kategorie"
    assert verlauf[0]["felder"][0]["alt"] == "Architekt/in"
    assert verlauf[0]["felder"][0]["neu"] == "Bauingenieur/in (Statik)"


def test_nur_schreibweise_unterschied_erzeugt_keinen_verlauf(tmp_db):
    """Wie beim Zusammenfuehren (queries.merge_kontakt): Gross-/Kleinschreibung und
    Mehrfach-Leerzeichen sind kein inhaltlicher Unterschied."""
    kid = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    kontakt = queries.get_kontakt(tmp_db, kid)
    neu = dict(kontakt)
    neu["vorname"] = "  anna  "
    queries.update_kontakt(tmp_db, kid, neu)
    assert queries.kontakt_verlauf(tmp_db, kid) == []


def test_wiederherstellen_setzt_alten_wert_und_protokolliert_sich_selbst(tmp_db):
    kid = _kontakt_mit_adresse(tmp_db)
    kontakt = queries.get_kontakt(tmp_db, kid)
    neu = dict(kontakt)
    neu["adressen"] = [kontakt["adressen"][0], {**kontakt["adressen"][1], "strasse": "Neue Gasse 8"}]
    queries.update_kontakt(tmp_db, kid, neu, quelle="kontakte_app")

    ereignis_id = queries.kontakt_verlauf(tmp_db, kid)[0]["id"]
    ereignis = queries.verlauf_ereignis(tmp_db, ereignis_id)

    aktuell = queries.get_kontakt(tmp_db, kid)
    wiederhergestellt = dict(aktuell)
    for f in ereignis["felder"]:
        wiederhergestellt[f["feld"]] = f["alt_wert"]
    queries.update_kontakt(tmp_db, kid, wiederhergestellt, quelle="wiederherstellung")

    strassen = {a["strasse"] for a in queries.get_kontakt(tmp_db, kid)["adressen"]}
    assert "Alte Gasse 3" in strassen
    assert "Neue Gasse 8" not in strassen

    verlauf = queries.kontakt_verlauf(tmp_db, kid)
    assert len(verlauf) == 2
    assert verlauf[0]["quelle"] == "wiederherstellung"  # neuestes zuerst
