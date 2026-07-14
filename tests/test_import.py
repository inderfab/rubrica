import textwrap

from db import queries
from importer.vcard import importiere, parse_vcf, finde_match


VCF_NEU = textwrap.dedent("""\
    BEGIN:VCARD
    VERSION:3.0
    N:Muster;Anna;;;
    FN:Anna Muster
    ORG:Muster AG
    TEL;TYPE=CELL:+41 79 123 45 67
    EMAIL;TYPE=WORK:anna@example.com
    END:VCARD
""")

VCF_VOLLSTAENDIG = textwrap.dedent("""\
    BEGIN:VCARD
    VERSION:3.0
    N:Beispiel;Carla;;;
    FN:Carla Beispiel
    ORG:Beispiel AG
    ADR;TYPE=WORK:;;Musterstrasse 1;Zuerich;ZH;8000;Schweiz
    URL;TYPE=HOME:https://carla-beispiel.ch
    NOTE:Erstkontakt ueber Messe
    TEL;TYPE=CELL:+41 79 111 22 33
    EMAIL;TYPE=WORK:carla@beispiel.ch
    END:VCARD
""")

VCF_GRUPPE = textwrap.dedent("""\
    BEGIN:VCARD
    VERSION:3.0
    N:Muster;Anna;;;
    FN:Anna Muster
    UID:anna-uid
    TEL;TYPE=CELL:+41791234567
    END:VCARD
    BEGIN:VCARD
    VERSION:3.0
    FN:Projekt X
    UID:gruppe-uid
    X-ADDRESSBOOKSERVER-KIND:group
    X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:anna-uid
    END:VCARD
""")


def test_parse_vcf_extrahiert_felder():
    kontakte = parse_vcf(VCF_NEU)
    assert len(kontakte) == 1
    k = kontakte[0]
    assert k["vorname"] == "Anna"
    assert k["nachname"] == "Muster"
    assert k["firma"] == "Muster AG"
    assert k["telefonnummern"][0]["nummer"] == "+41 79 123 45 67"
    assert k["emails"][0]["email"] == "anna@example.com"


def test_parse_vcf_gruppenzugehoerigkeit():
    kontakte = parse_vcf(VCF_GRUPPE)
    assert len(kontakte) == 1
    assert kontakte[0]["gruppen"] == ["Projekt X"]


def test_importiere_uebernimmt_gruppen_standardmaessig_ohne_flag(tmp_db):
    # Frueher eine Checkbox im Import-Formular, die faktisch wirkungslos war -
    # jetzt Standardverhalten (siehe web/imports.py).
    kontakt_ids = importiere(tmp_db, VCF_GRUPPE)
    kontakt = queries.get_kontakt(tmp_db, kontakt_ids[0])
    assert [p["name"] for p in kontakt["projekte"]] == ["Projekt X"]


def test_parse_vcf_mappt_englische_apple_typen_auf_direkt_privat_allgemein():
    vcf = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        N:Muster;Anna;;;
        FN:Anna Muster
        TEL;TYPE=WORK:+41 52 111 11 11
        TEL;TYPE=CELL:+41 79 222 22 22
        TEL;TYPE=MAIN:+41 52 333 33 33
        EMAIL;TYPE=INTERNET:anna@example.com
        END:VCARD
    """)
    k = parse_vcf(vcf)[0]
    telefon_typen = {t["nummer"]: t["typ"] for t in k["telefonnummern"]}
    assert telefon_typen["+41 52 111 11 11"] == "Direkt"
    assert telefon_typen["+41 79 222 22 22"] == "Privat"
    assert telefon_typen["+41 52 333 33 33"] == "Allgemein"
    assert k["emails"][0]["typ"] == "Direkt"


def test_import_ohne_treffer_legt_neuen_kontakt_direkt_an(tmp_db):
    kontakt_ids = importiere(tmp_db, VCF_NEU, gruppen_als_ordner=False)
    assert len(kontakt_ids) == 1

    kontakt = queries.get_kontakt(tmp_db, kontakt_ids[0])
    assert kontakt["nachname"] == "Muster"
    assert kontakt["firma"] == "Muster AG"
    assert tmp_db.execute("SELECT COUNT(*) FROM kontakte").fetchone()[0] == 1


def test_import_mit_treffer_mergt_direkt_in_bestehenden_kontakt(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "emails": [{"typ": "arbeit", "email": "anna@example.com"}],
    })

    kontakt_ids = importiere(tmp_db, VCF_NEU, gruppen_als_ordner=False)
    assert kontakt_ids == [kontakt_id]

    # Kein zweiter Kontakt darf entstanden sein, Firma wird ergaenzt
    assert tmp_db.execute("SELECT COUNT(*) FROM kontakte").fetchone()[0] == 1
    kontakt = queries.get_kontakt(tmp_db, kontakt_id)
    assert kontakt["firma"] == "Muster AG"


def test_import_mergt_statt_ueberschreibt(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [{"typ": "festnetz", "nummer": "044 123 45 67"}],
        "emails": [{"typ": "arbeit", "email": "anna@example.com"}],
    })
    importiere(tmp_db, VCF_NEU, gruppen_als_ordner=False)

    kontakt = queries.get_kontakt(tmp_db, kontakt_id)
    assert kontakt["firma"] == "Muster AG"  # aus dem Import uebernommen
    # bestehende Festnetznummer bleibt erhalten, neue Mobilnummer wird ergaenzt
    nummern = {t["nummer"] for t in kontakt["telefonnummern"]}
    assert "044 123 45 67" in nummern
    assert "+41 79 123 45 67" in nummern


def test_finde_match_ueber_telefonnummer_normalisiert(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Bob", "nachname": "Beispiel",
        "telefonnummern": [{"typ": "mobil", "nummer": "079 123 45 67"}],
    })
    treffer = finde_match(tmp_db, {"emails": [], "telefonnummern": [{"nummer": "+41791234567"}]})
    assert treffer == kontakt_id


def test_parse_vcf_extrahiert_adresse_url_notizen():
    kontakte = parse_vcf(VCF_VOLLSTAENDIG)
    assert len(kontakte) == 1
    k = kontakte[0]
    assert k["adressen"] == [{
        "typ": "work", "strasse": "Musterstrasse 1", "plz": "8000",
        "ort": "Zuerich", "region": "ZH", "land": "Schweiz",
    }]
    assert k["urls"] == [{"typ": "home", "url": "https://carla-beispiel.ch"}]
    assert k["notizen"] == "Erstkontakt ueber Messe"


def test_import_uebernimmt_adresse_url_notizen_direkt(tmp_db):
    kontakt_ids = importiere(tmp_db, VCF_VOLLSTAENDIG, gruppen_als_ordner=False)

    kontakt = queries.get_kontakt(tmp_db, kontakt_ids[0])
    assert kontakt["notizen"] == "Erstkontakt ueber Messe"
    assert kontakt["adressen"][0]["ort"] == "Zuerich"
    assert kontakt["urls"][0]["url"] == "https://carla-beispiel.ch"


def test_merge_ergaenzt_adresse_und_haengt_notizen_an(tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Carla", "nachname": "Beispiel",
        "notizen": "Alte Notiz",
        "emails": [{"typ": "arbeit", "email": "carla@beispiel.ch"}],
    })
    kontakt_ids = importiere(tmp_db, VCF_VOLLSTAENDIG, gruppen_als_ordner=False)
    assert kontakt_ids == [kontakt_id]

    kontakt = queries.get_kontakt(tmp_db, kontakt_id)
    assert "Alte Notiz" in kontakt["notizen"]
    assert "Erstkontakt ueber Messe" in kontakt["notizen"]
    assert len(kontakt["adressen"]) == 1
    assert len(kontakt["urls"]) == 1


def test_batch_import_vieler_synthetischer_kontakte(tmp_db):
    vcards = []
    for i in range(60):
        vcards.append(textwrap.dedent(f"""\
            BEGIN:VCARD
            VERSION:3.0
            N:Nachname{i};Vorname{i};;;
            FN:Vorname{i} Nachname{i}
            ORG:Firma {i} AG
            ADR;TYPE=WORK:;;Teststrasse {i};Teststadt;ZH;800{i % 10};Schweiz
            URL;TYPE=WORK:https://firma{i}.ch
            NOTE:Testkontakt Nummer {i}
            TEL;TYPE=CELL:+41 79 {i:03d} {i:02d} {i:02d}
            EMAIL;TYPE=WORK:kontakt{i}@firma{i}.ch
            END:VCARD
        """))
    grosse_datei = "".join(vcards)

    kontakt_ids = importiere(tmp_db, grosse_datei, gruppen_als_ordner=False)
    assert len(kontakt_ids) == 60

    assert tmp_db.execute("SELECT COUNT(*) FROM kontakte").fetchone()[0] == 60
    assert tmp_db.execute("SELECT COUNT(*) FROM adressen").fetchone()[0] == 60
    assert tmp_db.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 60
