from export import generator


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
