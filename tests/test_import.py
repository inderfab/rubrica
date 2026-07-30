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
    assert kontakte[0]["gruppen_uids"] == {"Projekt X": "gruppe-uid"}


def test_importiere_uebernimmt_gruppen_standardmaessig_ohne_flag(tmp_db):
    # Frueher eine Checkbox im Import-Formular, die faktisch wirkungslos war -
    # jetzt Standardverhalten (siehe web/imports.py).
    kontakt_ids = importiere(tmp_db, VCF_GRUPPE)
    kontakt = queries.get_kontakt(tmp_db, kontakt_ids[0])
    assert [p["name"] for p in kontakt["projekte"]] == ["Projekt X"]


def test_erneuter_import_nach_ordner_umbenennung_legt_keinen_zweiten_ordner_an(tmp_db):
    # Regression (Nutzer-Wunsch "Import robuster machen"): ein in Rubrica umbenannter
    # Ordner wurde beim erneuten Kontakte.app-Import bisher nicht wiedererkannt (Matching
    # lief rein ueber den - jetzt geaenderten - Namen) und dadurch unter dem alten
    # Apple-Gruppennamen ein zweiter, verwaister Ordner angelegt. Die stabile
    # Apple-Gruppen-UID (siehe queries.get_or_create_projekt_von_apple_gruppe) verhindert das.
    kontakt_ids = importiere(tmp_db, VCF_GRUPPE)
    ordner_id = queries.list_projekte(tmp_db)[0]["id"]
    queries.rename_projekt(tmp_db, ordner_id, "Projekt X (umbenannt)")

    kontakt_ids_2 = importiere(tmp_db, VCF_GRUPPE)

    assert kontakt_ids_2 == kontakt_ids  # derselbe Kontakt, kein Duplikat
    ordner = queries.list_projekte(tmp_db)
    assert len(ordner) == 1  # kein zweiter "Projekt X"-Ordner entstanden
    assert ordner[0]["name"] == "Projekt X (umbenannt)"  # Umbenennung bleibt erhalten
    kontakt = queries.get_kontakt(tmp_db, kontakt_ids[0])
    assert [p["name"] for p in kontakt["projekte"]] == ["Projekt X (umbenannt)"]


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
    assert "+41 44 123 45 67" in nummern
    assert "+41 79 123 45 67" in nummern


def test_import_verschiedene_kontakte_mit_gleichem_festnetz_werden_nicht_zusammengelegt(tmp_db):
    # Regression (Nutzer-Meldung): zwei verschiedene Personen mit gemeinsamem
    # Festnetzanschluss (z.B. Ehepaar) wurden zuvor ueber den Telefon-Abgleich in
    # finde_match() faelschlich als derselbe Kontakt erkannt und automatisch (ohne
    # Rueckfrage) zusammengefuehrt - siehe importer/vcard.py._finde_match_fuer_import.
    vcf = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        N:Kunz;Peter;;;
        FN:Peter Kunz
        TEL;TYPE=HOME:044 000 00 00
        EMAIL;TYPE=WORK:peter@beispiel.ch
        END:VCARD
        BEGIN:VCARD
        VERSION:3.0
        N:Beispiel;Claudia;;;
        FN:Claudia Beispiel
        TEL;TYPE=HOME:044 000 00 00
        EMAIL;TYPE=WORK:claudia@beispiel.ch
        END:VCARD
    """)
    kontakt_ids = importiere(tmp_db, vcf, gruppen_als_ordner=False)

    assert len(kontakt_ids) == 2
    assert len(set(kontakt_ids)) == 2
    assert tmp_db.execute("SELECT COUNT(*) FROM kontakte").fetchone()[0] == 2

    nachnamen = {queries.get_kontakt(tmp_db, kid)["nachname"] for kid in kontakt_ids}
    assert nachnamen == {"Kunz", "Beispiel"}
    for kid in kontakt_ids:
        kontakt = queries.get_kontakt(tmp_db, kid)
        # Jeder behaelt seine eigene Mailadresse - keine Vermischung.
        mails = {e["email"] for e in kontakt["emails"]}
        if kontakt["nachname"] == "Kunz":
            assert mails == {"peter@beispiel.ch"}
        else:
            assert mails == {"claudia@beispiel.ch"}


def test_import_erkennt_erneuten_import_ueber_apple_uid(tmp_db):
    vcf_alt = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        UID:peter-kunz-uid
        N:Kunz;Peter;;;
        FN:Peter Kunz
        EMAIL;TYPE=WORK:peter@alt.ch
        END:VCARD
    """)
    kontakt_ids = importiere(tmp_db, vcf_alt, gruppen_als_ordner=False)
    kontakt_id = kontakt_ids[0]

    # Peter hat seine Mailadresse gewechselt - ohne UID-Abgleich wuerde die reine
    # E-Mail-Heuristik hier keinen Treffer mehr finden und einen Dublikat anlegen.
    vcf_neu = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        UID:peter-kunz-uid
        N:Kunz;Peter;;;
        FN:Peter Kunz
        EMAIL;TYPE=WORK:peter@neu.ch
        END:VCARD
    """)
    kontakt_ids_2 = importiere(tmp_db, vcf_neu, gruppen_als_ordner=False)

    assert kontakt_ids_2 == [kontakt_id]
    assert tmp_db.execute("SELECT COUNT(*) FROM kontakte").fetchone()[0] == 1
    mails = {e["email"] for e in queries.get_kontakt(tmp_db, kontakt_id)["emails"]}
    assert mails == {"peter@alt.ch", "peter@neu.ch"}  # ergaenzt, nicht ersetzt


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


def test_list_import_zusammenfuehrungen_zeigt_nur_gemergte_dubletten(tmp_db):
    # Nutzer-Nachfrage bei einem grossen Import ("importiert" < "gefunden"): sind das
    # wirklich Dubletten? Diese Abfrage macht die zusammengefuehrten Eintraege sichtbar.
    vcf_zwei_verschiedene = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        N:Kunz;Peter;;;
        FN:Peter Kunz
        EMAIL;TYPE=WORK:peter@beispiel.ch
        END:VCARD
        BEGIN:VCARD
        VERSION:3.0
        N:Beispiel;Claudia;;;
        FN:Claudia Beispiel
        EMAIL;TYPE=WORK:claudia@beispiel.ch
        END:VCARD
    """)
    importiere(tmp_db, vcf_zwei_verschiedene, gruppen_als_ordner=False)
    assert queries.list_import_zusammenfuehrungen(tmp_db) == []  # beides neue Kontakte, keine Dublette

    vcf_dublette = textwrap.dedent("""\
        BEGIN:VCARD
        VERSION:3.0
        N:Kunz;Peter;;;
        FN:Peter Kunz
        EMAIL;TYPE=WORK:peter@beispiel.ch
        TEL;TYPE=HOME:044 111 22 33
        END:VCARD
    """)
    importiere(tmp_db, vcf_dublette, gruppen_als_ordner=False)

    zusammenfuehrungen = queries.list_import_zusammenfuehrungen(tmp_db)
    assert len(zusammenfuehrungen) == 1
    assert zusammenfuehrungen[0]["rohdaten"]["emails"][0]["email"] == "peter@beispiel.ch"
    assert zusammenfuehrungen[0]["bestehender_kontakt"]["nachname"] == "Kunz"
