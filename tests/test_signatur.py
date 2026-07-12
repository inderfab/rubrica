from importer.signatur import parse_signatur


SIG_TYPISCH = """\
Freundliche Grüsse

Anna Brändli
Projektleiterin

Strut Architekten AG
Neuwiesenstrasse 69
8400 Winterthur

Tel. +41 52 214 20 21
Mobile +41 79 697 40 13
anna.braendli@strut.ch
www.strut.ch
"""


def test_email_und_web():
    d = parse_signatur(SIG_TYPISCH)
    assert {"typ": "arbeit", "email": "anna.braendli@strut.ch"} in d["emails"]
    assert any(u["url"] == "www.strut.ch" for u in d["urls"])
    # E-Mail-Domain darf nicht als URL auftauchen
    assert not any("@" in u["url"] for u in d["urls"])


def test_telefon_klassifikation():
    d = parse_signatur(SIG_TYPISCH)
    typen = {t["typ"]: t["nummer"] for t in d["telefonnummern"]}
    assert "arbeit" in typen and "52" in typen["arbeit"]
    assert "mobil" in typen and "79" in typen["mobil"]


def test_firma_und_name():
    d = parse_signatur(SIG_TYPISCH)
    assert d["firma"] == "Strut Architekten AG"
    assert d["vorname"] == "Anna"
    assert d["nachname"] == "Brändli"


def test_adresse():
    d = parse_signatur(SIG_TYPISCH)
    assert len(d["adressen"]) == 1
    a = d["adressen"][0]
    assert a["strasse"] == "Neuwiesenstrasse 69"
    assert a["plz"] == "8400"
    assert a["ort"] == "Winterthur"


def test_rolle():
    d = parse_signatur(SIG_TYPISCH)
    assert "Projektleiterin" in d["rolle"]


def test_mobil_ohne_label_per_vorwahl():
    d = parse_signatur("Max Muster\nMuster GmbH\n079 123 45 67\n044 321 65 43")
    typen = {t["typ"] for t in d["telefonnummern"]}
    assert "mobil" in typen  # 079... als Mobil erkannt
    assert "arbeit" in typen  # 044... als Festnetz


def test_leere_signatur_bricht_nicht_ab():
    d = parse_signatur("")
    assert d["emails"] == [] and d["telefonnummern"] == []
    assert d["vorname"] == "" and d["firma"] == ""


def test_nur_email_zeile():
    d = parse_signatur("bitte melden bei info@beispiel.ch")
    assert d["emails"][0]["email"] == "info@beispiel.ch"


def test_dubletten_werden_entfernt():
    d = parse_signatur("a@b.ch\na@b.ch\n079 111 22 33\n079 111 22 33")
    assert len(d["emails"]) == 1
    assert len(d["telefonnummern"]) == 1


def test_kompakte_signatur_mit_labels():
    sig = "Dr. Hans Meier | Geologe\nGeoTest AG\nT: 044 123 45 67  F: 044 123 45 68\nM: 079 888 77 66\nhans.meier@geotest.ch"
    d = parse_signatur(sig)
    typen = {t["typ"] for t in d["telefonnummern"]}
    assert typen == {"arbeit", "fax", "mobil"}
    assert d["firma"] == "GeoTest AG"
    assert d["emails"][0]["email"] == "hans.meier@geotest.ch"
