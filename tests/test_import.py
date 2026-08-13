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


def test_parse_vcf_mappt_apple_typen_auf_die_festen_kategorien():
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
    # CELL ist geschaeftlich, solange nichts auf privat hindeutet - Telefon kennt
    # seit 2026-08-06 kein "Allgemein" mehr (siehe web/contacts.py TELEFON_TYPEN).
    assert telefon_typen["+41 79 222 22 22"] == "Direkt Handy"
    assert telefon_typen["+41 52 333 33 33"] == "Direkt"
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
        "typ": "Arbeit", "strasse": "Musterstrasse 1", "plz": "8000",
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


# ── Bezeichnungen aus Kontakte.app ────────────────────────────────────────────

def _karte(zeilen: str) -> dict:
    import vobject
    from importer import vcard
    return vcard._parse_kontakt(vobject.readOne(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Muster;Anna;;;\r\nFN:Anna Muster\r\n"
        + zeilen + "END:VCARD\r\n"
    ))


def test_private_email_aus_kontakte_app_bleibt_privat(tmp_db):
    """Regression: Apple schreibt `EMAIL;type=INTERNET;type=HOME`. Wer nur den
    ersten TYPE liest, sieht "internet", mappt auf "Direkt" - und die private
    Adresse steht damit auf der Adressliste, die aus dem Haus geht."""
    kontakt = _karte("EMAIL;type=INTERNET;type=HOME:privat@beispiel.ch\r\n")
    assert kontakt["emails"][0]["typ"] == "Privat"


def test_privatnummer_hinter_pref_bleibt_privat(tmp_db):
    kontakt = _karte("TEL;type=pref;type=HOME:+41 44 444 44 44\r\n")
    assert kontakt["telefonnummern"][0]["typ"] == "Privat"


def test_eigene_bezeichnung_aus_kontakte_app_bleibt_erhalten(tmp_db):
    """Eine selbst vergebene Bezeichnung sind die Worte des Nutzers - sie wird als
    eigene Kategorie uebernommen statt still auf "Direkt" zu fallen. Einsortieren
    laesst sie sich danach unter /einstellungen/kategorien."""
    kontakt = _karte("item1.TEL;type=pref:+41 44 111 11 11\r\nitem1.X-ABLabel:Sekretariat\r\n")
    assert kontakt["telefonnummern"][0]["typ"] == "Sekretariat"


def test_apple_standardbezeichnung_wird_zugeordnet(tmp_db):
    """Apples eigene Schreibweise fuer Standardbezeichnungen (`_$!<Work>!$_`) darf
    nicht als eigene Kategorie durchgehen."""
    kontakt = _karte("item1.TEL:+41 44 222 22 22\r\nitem1.X-ABLabel:_$!<Work>!$_\r\n")
    assert kontakt["telefonnummern"][0]["typ"] == "Direkt"


def test_eigene_bezeichnung_uebernimmt_bestehende_schreibweise(tmp_db, monkeypatch):
    """Damit "direkt" aus Kontakte.app nicht als zweiter Wert neben "Direkt" steht."""
    kontakt = _karte("item1.TEL:+41 44 222 22 22\r\nitem1.X-ABLabel:pRIVAT hANDY\r\n")
    assert kontakt["telefonnummern"][0]["typ"] == "Privat Handy"


def test_merge_behaelt_den_namen_des_bestehenden_kontakts(tmp_db):
    """Regression mit Datenverlust (Nutzer-Meldung): zwei Personen derselben Firma
    wurden zu einer zusammengefasst, die zweite war anschliessend verschwunden. Ein
    Merge entsteht aus einem Duplikat-VERDACHT - eine gemeinsame Zentralennummer
    genügt. Gewinnt dabei der Name aus dem Vorschlag, überschreibt er
    stillschweigend die Identität eines bestehenden Kontakts."""
    from db import queries

    bestehender = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster", "firma": "Muster AG",
        "telefonnummern": [{"typ": "Direkt", "nummer": "+41 52 111 11 11"}],
    })

    queries.merge_kontakt(tmp_db, bestehender, {
        "vorname": "Bruno", "nachname": "Beispiel", "firma": "Muster AG",
        "telefonnummern": [{"typ": "Direkt", "nummer": "+41 52 111 11 11"}],
        "emails": [{"typ": "Direkt", "email": "bruno@beispiel.ch"}],
    })

    kontakt = queries.get_kontakt(tmp_db, bestehender)
    assert (kontakt["vorname"], kontakt["nachname"]) == ("Anna", "Muster")
    # Die mitgebrachten Kontaktdaten kommen weiterhin dazu.
    assert any(e["email"] == "bruno@beispiel.ch" for e in kontakt["emails"])


def test_merge_fuellt_den_namen_bei_einem_namenlosen_firmeneintrag(tmp_db):
    """Gegenprobe: ein Eintrag, der nur die Firma trägt (typische Zentrale), soll
    den Namen aus dem Vorschlag durchaus bekommen."""
    from db import queries

    firma = queries.create_kontakt(tmp_db, {"vorname": "", "nachname": "", "firma": "Muster AG"})
    queries.merge_kontakt(tmp_db, firma, {"vorname": "Anna", "nachname": "Muster", "firma": ""})

    kontakt = queries.get_kontakt(tmp_db, firma)
    assert (kontakt["vorname"], kontakt["nachname"], kontakt["firma"]) == ("Anna", "Muster", "Muster AG")


def test_merge_verdoppelt_keine_adresse_wegen_schreibweise(tmp_db):
    """Nutzer-Meldung: beim Zusammenführen standen danach zwei identische Adressen
    da — einmal gross, einmal klein geschrieben. Der Vorschlag kommt aus einer
    anderen Quelle und schreibt dieselbe Angabe oft anders."""
    from db import queries

    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "adressen": [{"typ": "Arbeit", "strasse": "Musterstrasse 1", "plz": "8000",
                      "ort": "Zürich", "region": "", "land": ""}],
        "emails": [{"typ": "Direkt", "email": "Anna@Beispiel.CH"}],
        "telefonnummern": [{"typ": "Direkt", "nummer": "+41 52 111 11 11"}],
    })

    queries.merge_kontakt(tmp_db, kontakt_id, {
        "adressen": [{"typ": "Arbeit", "strasse": "musterstrasse  1", "plz": "8000",
                      "ort": "zürich", "region": "", "land": ""}],
        "emails": [{"typ": "Direkt", "email": "anna@beispiel.ch"}],
        "telefonnummern": [{"typ": "Direkt", "nummer": "+41 52 111 1111"}],
    })

    kontakt = queries.get_kontakt(tmp_db, kontakt_id)
    assert len(kontakt["adressen"]) == 1, "Adresse wegen Schreibweise verdoppelt"
    assert len(kontakt["emails"]) == 1, "E-Mail wegen Schreibweise verdoppelt"
    assert len(kontakt["telefonnummern"]) == 1, "Nummer wegen Formatierung verdoppelt"


def test_merge_ergaenzt_eine_wirklich_andere_adresse(tmp_db):
    """Gegenprobe: eine echte Zweitadresse muss dazukommen."""
    from db import queries

    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "adressen": [{"typ": "Arbeit", "strasse": "Musterstrasse 1", "plz": "8000",
                      "ort": "Zürich", "region": "", "land": ""}],
    })
    queries.merge_kontakt(tmp_db, kontakt_id, {
        "adressen": [{"typ": "Baustelle", "strasse": "Baustellenweg 9", "plz": "8400",
                      "ort": "Winterthur", "region": "", "land": ""}],
    })

    assert len(queries.get_kontakt(tmp_db, kontakt_id)["adressen"]) == 2
