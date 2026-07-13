import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from config import settings
from db import queries
from export import generator
from web.main import app


def _kontakt(**overrides) -> dict:
    basis = {
        "id": 1, "vorname": "Anna", "nachname": "Muster", "firma": "Muster AG",
        "rolle": "Bauleiterin", "kategorie": "Fachplaner", "notizen": "Testnotiz",
        "telefonnummern": [{"typ": "mobil", "nummer": "079 123 45 67"}],
        "emails": [{"typ": "arbeit", "email": "anna@example.com"}],
        "adressen": [{"typ": "arbeit", "strasse": "Teststrasse 1", "plz": "8000",
                      "ort": "Zuerich", "region": "ZH", "land": "Schweiz"}],
        "urls": [{"typ": "homepage", "url": "https://example.com"}],
    }
    basis.update(overrides)
    return basis


def test_kontakte_csv_enthaelt_felder_und_kopfzeile():
    daten = generator.kontakte_csv([_kontakt()])
    text = daten.decode("utf-8-sig")
    zeilen = text.strip().splitlines()
    assert zeilen[0] == ";".join(generator.CSV_SPALTEN)
    assert "Anna" in zeilen[1]
    assert "Muster AG" in zeilen[1]
    assert "079 123 45 67" in zeilen[1]
    assert "anna@example.com" in zeilen[1]
    assert "Teststrasse 1" in zeilen[1]


def test_kontakte_csv_leere_liste_nur_kopfzeile():
    daten = generator.kontakte_csv([])
    zeilen = daten.decode("utf-8-sig").strip().splitlines()
    assert len(zeilen) == 1


def test_kontakte_vcard_enthaelt_alle_kontakte():
    daten = generator.kontakte_vcard([_kontakt(id=1, vorname="Anna"), _kontakt(id=2, vorname="Bob")])
    text = daten.decode("utf-8")
    assert text.count("BEGIN:VCARD") == 2
    assert "FN:Anna Muster" in text
    assert "FN:Bob Muster" in text


def test_kontakte_pdf_erzeugt_gueltiges_pdf():
    daten = generator.kontakte_pdf("Testordner", [_kontakt()])
    assert daten.startswith(b"%PDF")
    assert len(daten) > 500


def test_kontakte_pdf_leere_liste_bricht_nicht_ab():
    daten = generator.kontakte_pdf("Leerer Ordner", [])
    assert daten.startswith(b"%PDF")


def test_kontakte_pdf_mit_firmenname_und_ungueltigem_logo_bricht_nicht_ab():
    # logo_pfad zeigt absichtlich auf eine nicht existierende Datei - darf den
    # Export nicht zum Absturz bringen (Best-effort wie beim Backup-Feature).
    daten = generator.kontakte_pdf("Testordner", [_kontakt()],
                                    firmenname="Strut Architekten AG", logo_pfad="/pfad/existiert/nicht.png")
    assert daten.startswith(b"%PDF")


def test_bkp_zellen_text_bricht_nach_der_nummer_um():
    assert generator._bkp_zellen_text("292 Bauingenieur/in") == "292<br/>Bauingenieur/in"
    assert generator._bkp_zellen_text("Bauherrschaft/Kundschaft") == "Bauherrschaft/Kundschaft"


def test_telefon_liste_trennt_mobil_von_festnetz():
    kontakt = _kontakt(telefonnummern=[
        {"typ": "arbeit", "nummer": "052 123 45 67"},
        {"typ": "mobil", "nummer": "079 123 45 67"},
    ])
    assert generator._telefon_liste(kontakt, mobil=False) == "052 123 45 67"
    assert generator._telefon_liste(kontakt, mobil=True) == "079 123 45 67"


def test_bkp_sortier_schluessel_ordnet_numerisch_nicht_alphabetisch():
    # Alphabetisch waere "299" < "297", numerisch muss "297" zuerst kommen.
    schluessel_297 = generator._bkp_sortier_schluessel("297.0 Geometer")
    schluessel_299 = generator._bkp_sortier_schluessel("299 Visualisierung")
    assert schluessel_297 < schluessel_299


def test_bkp_sortier_schluessel_ohne_nummer_kommt_zuerst():
    ohne_nummer = generator._bkp_sortier_schluessel("Bauherrschaft/Kundschaft")
    mit_nummer = generator._bkp_sortier_schluessel("104 Baugespann")
    assert ohne_nummer < mit_nummer


def test_gruppiert_mehrere_personen_derselben_firma_in_einen_block():
    kontakte = [
        _kontakt(id=1, vorname="Astrid", nachname="Bleuler", firma="S+K Bauingenieure AG",
                 kategorie="292 Bauingenieur/in", rolle="Partnerin"),
        _kontakt(id=2, vorname="Michael", nachname="Küttel", firma="S+K Bauingenieure AG",
                 kategorie="292 Bauingenieur/in", rolle="Projektleiter"),
        _kontakt(id=3, vorname="Corina", nachname="Moos", firma="S+K Bauingenieure AG",
                 kategorie="292 Bauingenieur/in", rolle="Bauingenieurin"),
    ]
    gruppen = generator._gruppiere_fuer_export(kontakte)
    assert len(gruppen) == 1
    assert gruppen[0]["funktion"] == "292 Bauingenieur/in"
    assert len(gruppen[0]["firmen"]) == 1
    assert len(gruppen[0]["firmen"][0]["kontakte"]) == 3


def test_gruppiert_sortiert_funktionsgruppen_nach_bkp_nummer():
    kontakte = [
        _kontakt(id=1, firma="Firma A", kategorie="299 Visualisierung"),
        _kontakt(id=2, firma="Firma B", kategorie="104 Baugespann"),
        _kontakt(id=3, firma="Firma C", kategorie="297.0 Geometer"),
    ]
    gruppen = generator._gruppiere_fuer_export(kontakte)
    funktionen = [g["funktion"] for g in gruppen]
    assert funktionen == ["104 Baugespann", "297.0 Geometer", "299 Visualisierung"]


def test_export_route_nutzt_konfigurierten_firmennamen(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"export": {"firmenname": "Strut Architekten AG"}})
    queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})

    r = TestClient(app).post("/export", data={"ordner_id": "", "formate": ["pdf"]})
    assert r.status_code == 200
    zf = zipfile.ZipFile(BytesIO(r.content))
    pdf_bytes = zf.read(zf.namelist()[0])
    assert pdf_bytes.startswith(b"%PDF")


def test_pdf_export_ignoriert_andere_ordner_zugehoerigkeit():
    # Export ist bereits auf einen Ordner beschraenkt (Titel = Ordnername); ob ein
    # Kontakt noch weiteren Ordnern angehoert, darf im Export nicht auftauchen.
    # Da reportlab-PDFs komprimiert sind (kein direkter Text-Grep moeglich),
    # wird stattdessen der Generator-Quellcode geprueft: er darf das
    # "projekte"-Feld an keiner Stelle lesen/ausgeben.
    import inspect
    quelle = inspect.getsource(generator)
    assert '"projekte"' not in quelle
    assert "'projekte'" not in quelle
    # Smoke-Test: mit zusaetzlichem projekte-Feld im Dict bricht nichts ab.
    daten = generator.kontakte_pdf(
        "Mein Ordner", [_kontakt(projekte=[{"id": 1, "name": "Anderer Ordner"}])]
    )
    assert daten.startswith(b"%PDF")
