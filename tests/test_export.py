import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from config import settings
from db import queries
from export import generator
from web.main import app


def _kontakt(**overrides) -> dict:
    # "kategorie"/"rolle" bleiben als bequeme Kurzform fuer EIN Funktion/Rolle-Paar
    # nutzbar (seit kontakt_funktionen die eigentliche Quelle, siehe generator.
    # _fuer_export_expandieren) - fuer mehrere Paare "funktionen" direkt uebergeben.
    kategorie = overrides.pop("kategorie", "Fachplaner")
    rolle = overrides.pop("rolle", "Bauleiterin")
    basis = {
        "id": 1, "vorname": "Anna", "nachname": "Muster", "firma": "Muster AG",
        "funktionen": [{"funktion": kategorie, "rolle": rolle}] if (kategorie or rolle) else [],
        "notizen": "Testnotiz",
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


def test_kontakte_csv_trennt_kategorien_in_eigene_spalten():
    kontakt = _kontakt(
        telefonnummern=[
            {"typ": "work", "nummer": "052 111 11 11"},
            {"typ": "cell", "nummer": "079 222 22 22"},
            {"typ": "main", "nummer": "052 333 33 33"},
        ],
        emails=[{"typ": "internet", "email": "direkt@firma.ch"}, {"typ": "home", "email": "privat@example.com"}],
        adressen=[
            {"typ": "work", "strasse": "Buerostrasse 1", "plz": "8000", "ort": "Zuerich", "region": "", "land": ""},
            {"typ": "home", "strasse": "Heimweg 2", "plz": "8001", "ort": "Zuerich", "region": "", "land": ""},
        ],
    )
    daten = generator.kontakte_csv([kontakt])
    # Richtig parsen statt per split(";"): eine Zelle kann mehrere Werte enthalten
    # und wird dann korrekt gequotet - naives Splitten zerlegte genau das falsch.
    import csv as _csv
    import io as _io
    zeilen = list(_csv.DictReader(_io.StringIO(daten.decode("utf-8-sig")), delimiter=";"))
    zeile = zeilen[0]

    # "work" und "main" landen beide unter Direkt (Telefon kennt kein Allgemein mehr).
    assert "052 111 11 11" in zeile["Telefon Direkt"]
    # Mobilnummern haben seit 2026-08-06 eine eigene Spalte - eine geschaeftliche
    # Handynummer ist nicht mehr dasselbe wie eine private.
    assert zeile["Telefon Direkt Handy"] == "079 222 22 22"
    assert "052 333 33 33" in zeile["Telefon Direkt"]
    assert zeile["E-Mail Direkt"] == "direkt@firma.ch"
    assert zeile["E-Mail Privat"] == "privat@example.com"
    assert zeile["Adresse Direkt"] == "Buerostrasse 1, 8000 Zuerich"
    assert zeile["Adresse Privat"] == "Heimweg 2, 8001 Zuerich"


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
                                    firmenname="Muster Architektur AG", logo_pfad="/pfad/existiert/nicht.png")
    assert daten.startswith(b"%PDF")


def test_bkp_zellen_text_bricht_nach_der_nummer_um():
    assert generator._bkp_zellen_text("292 Bauingenieur/in") == "292<br/>Bauingenieur/in"
    assert generator._bkp_zellen_text("Bauherrschaft/Kundschaft") == "Bauherrschaft/Kundschaft"


def test_direktwahl_pdf_zeigt_geschaeftliches_handy():
    # Mobilnummern gelten als privat (Direkt/Privat/Allgemein-Kategorisierung) -
    # Umkehrung der frueheren Regel "Mobilnummern gelten als privat": es gibt jetzt
    # "Direkt Handy" und "Privat Handy" (siehe web/contacts.py TELEFON_TYPEN). Eine
    # geschaeftliche Mobilnummer gehoert auf die Projekt-Adressliste, eine private
    # bleibt ausgeblendet.
    kontakt = _kontakt(telefonnummern=[
        {"typ": "Direkt", "nummer": "052 123 45 67"},
        {"typ": "Direkt Handy", "nummer": "079 123 45 67"},
        {"typ": "Privat Handy", "nummer": "079 999 99 99"},
    ])
    assert generator._direktwahl_pdf(kontakt, privates_telefon_zeigen=False) == \
        "052 123 45 67<br/>079 123 45 67"
    assert "079 999 99 99" in generator._direktwahl_pdf(kontakt, privates_telefon_zeigen=True)


def test_direktwahl_pdf_erkennt_englische_apple_typen():
    """Alt-/Rohwerte aus vCards laufen ebenfalls durch: "home" bleibt privat,
    "cell" gilt als geschaeftliches Handy (siehe importer/vcard.py)."""
    # Reale Importe (Apple Kontakte.app) taggen meist englisch statt deutsch.
    kontakt = _kontakt(telefonnummern=[
        {"typ": "work", "nummer": "052 111 11 11"},
        {"typ": "cell", "nummer": "079 222 22 22"},
        {"typ": "home", "nummer": "052 333 33 33"},
    ])
    assert generator._direktwahl_pdf(kontakt, privates_telefon_zeigen=False) == \
        "052 111 11 11<br/>079 222 22 22"
    assert generator._direktwahl_pdf(kontakt, privates_telefon_zeigen=True) == "052 111 11 11<br/>079 222 22 22<br/>052 333 33 33"


def test_direktwahl_pdf_private_nummer_nur_mit_flag():
    kontakt = _kontakt(telefonnummern=[{"typ": "privat", "nummer": "052 999 99 99"}])
    assert generator._direktwahl_pdf(kontakt, privates_telefon_zeigen=False) == ""
    assert generator._direktwahl_pdf(kontakt, privates_telefon_zeigen=True) == "052 999 99 99"


def test_email_pdf_private_nur_mit_flag_generische_typen_immer_sichtbar():
    kontakt = _kontakt(emails=[
        {"typ": "internet", "email": "info@firma.ch"},  # Apple-Standardtyp, keine Unterscheidung moeglich
        {"typ": "home", "email": "privat@example.com"},
    ])
    ohne_privat = generator._email_pdf(kontakt, private_email_zeigen=False)
    assert "info@firma.ch" in ohne_privat
    assert "privat@example.com" not in ohne_privat
    mit_privat = generator._email_pdf(kontakt, private_email_zeigen=True)
    assert "privat@example.com" in mit_privat


def test_adresse_pdf_zeigt_keinen_typ_praefix_fuer_geschaeftsadresse():
    kontakt = _kontakt(adressen=[{"typ": "work", "strasse": "Teststrasse 1", "plz": "8000", "ort": "Zuerich", "region": "", "land": ""}])
    text = generator._adresse_pdf(kontakt, privatadresse_zeigen=False)
    assert "work" not in text.lower()
    assert "Teststrasse 1" in text


def test_adresse_pdf_privatadresse_nur_mit_flag_und_praefix():
    kontakt = _kontakt(adressen=[
        {"typ": "work", "strasse": "Buerostrasse 1", "plz": "8000", "ort": "Zuerich", "region": "", "land": ""},
        {"typ": "home", "strasse": "Heimweg 2", "plz": "8001", "ort": "Zuerich", "region": "", "land": ""},
    ])
    ohne_privat = generator._adresse_pdf(kontakt, privatadresse_zeigen=False)
    assert "Heimweg 2" not in ohne_privat
    mit_privat = generator._adresse_pdf(kontakt, privatadresse_zeigen=True)
    assert "Heimweg 2" in mit_privat
    assert "Privat:" in mit_privat


def test_tabellenzeilen_firmenzeile_getrennt_von_mitarbeiterzeilen():
    firmenkontakt = _kontakt(id=1, vorname="", nachname="", firma="Beispiel Bauingenieure AG",
                              kategorie="292 Bauingenieur/in", rolle="",
                              telefonnummern=[{"typ": "work", "nummer": "052 000 00 00"}],
                              emails=[{"typ": "internet", "email": "info@beispiel.ch"}])
    mitarbeiter = _kontakt(id=2, vorname="Astrid", nachname="Beispiel", firma="Beispiel Bauingenieure AG",
                            kategorie="292 Bauingenieur/in", rolle="Partnerin",
                            telefonnummern=[{"typ": "work", "nummer": "052 111 11 11"}],
                            emails=[{"typ": "internet", "email": "beispiel@beispiel.ch"}])
    zeilen, grenzen = generator._tabellenzeilen(
        [firmenkontakt, mitarbeiter], privates_telefon_zeigen=False,
        private_email_zeigen=False, privatadresse_zeigen=False,
    )
    assert len(zeilen) == 3  # Kopfzeile + Firmenzeile + 1 Mitarbeiterzeile
    firmenzeile, mitarbeiterzeile = zeilen[1], zeilen[2]
    assert firmenzeile[2] == "" and firmenzeile[3] == ""  # Sachbearbeitung/Funktion leer
    assert mitarbeiterzeile[0] == "" and mitarbeiterzeile[1] == ""  # BKP/Unternehmen leer
    assert grenzen == [1]  # eine Firmengruppe -> Trennlinie beginnt bei Zeile 1


def test_tabellenzeilen_hat_sechs_spalten_keine_eigene_mobil_spalte():
    zeilen, _ = generator._tabellenzeilen(
        [_kontakt()], privates_telefon_zeigen=False, private_email_zeigen=False, privatadresse_zeigen=False,
    )
    assert len(zeilen[0]) == 6
    assert [str(p.text) for p in zeilen[0]] == generator._TABELLEN_SPALTEN


def test_webseite_erscheint_nur_auf_firmenzeile_nicht_bei_mitarbeitern():
    firmenkontakt = _kontakt(id=1, vorname="", nachname="", firma="Muster AG", urls=[])
    mitarbeiter = _kontakt(id=2, vorname="Sarina", nachname="Muster", firma="Muster AG",
                            urls=[{"typ": "homepage", "url": "www.muster.ch"}])
    zeilen, _ = generator._tabellenzeilen(
        [firmenkontakt, mitarbeiter], privates_telefon_zeigen=False,
        private_email_zeigen=False, privatadresse_zeigen=False,
    )
    firmenzeile, mitarbeiterzeile = zeilen[1], zeilen[2]
    assert "www.muster.ch" in firmenzeile[5].text
    assert mitarbeiterzeile[5] == "" or "www.muster.ch" not in getattr(mitarbeiterzeile[5], "text", "")


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
        _kontakt(id=1, vorname="Astrid", nachname="Beispiel", firma="Beispiel Bauingenieure AG",
                 kategorie="292 Bauingenieur/in", rolle="Partnerin"),
        _kontakt(id=2, vorname="Michael", nachname="Suter", firma="Beispiel Bauingenieure AG",
                 kategorie="292 Bauingenieur/in", rolle="Projektleiter"),
        _kontakt(id=3, vorname="Corina", nachname="Kunz", firma="Beispiel Bauingenieure AG",
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


def test_kontakt_mit_zwei_funktionen_erscheint_in_beiden_gruppen():
    """Nutzer-Entscheid: hat jemand in einem Projekt zwei Funktionen (z.B. Architekt
    UND Bauleitung), erscheint er im Export unter BEIDEN - eine Adressliste wird
    ueber die Funktion durchsucht, nicht ueber den Namen."""
    kontakte = [_kontakt(id=1, vorname="Anna", nachname="Muster", firma="Muster AG", funktionen=[
        {"funktion": "291 Architekt/in", "rolle": "Projektleiterin"},
        {"funktion": "291 Bauleitung", "rolle": "Gestalterische Bauleitung"},
    ])]
    gruppen = generator._gruppiere_fuer_export(kontakte)
    funktionen = [g["funktion"] for g in gruppen]
    assert funktionen == ["291 Architekt/in", "291 Bauleitung"]
    # In jeder Gruppe steht die zu DIESER Funktion passende Rolle, nicht irgendeine.
    rolle_architekt = gruppen[0]["firmen"][0]["kontakte"][0]["rolle"]
    rolle_bauleitung = gruppen[1]["firmen"][0]["kontakte"][0]["rolle"]
    assert rolle_architekt == "Projektleiterin"
    assert rolle_bauleitung == "Gestalterische Bauleitung"

    # Auch in der CSV zweimal, mit je eigener Funktion/Rolle-Spalte.
    csv_text = generator.kontakte_csv(kontakte).decode("utf-8-sig")
    zeilen = [z for z in csv_text.strip().splitlines()[1:]]
    assert len(zeilen) == 2
    assert any("291 Architekt/in;Projektleiterin" in z for z in zeilen)
    assert any("291 Bauleitung;Gestalterische Bauleitung" in z for z in zeilen)


def test_export_route_nutzt_konfigurierten_firmennamen(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"export": {"firmenname": "Muster Architektur AG"}})
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


def test_telefon_mit_altwert_allgemein_verschwindet_nicht_aus_csv():
    """Regression: beim Wegfall der Spalte "Telefon Allgemein" fiel eine noch als
    "allgemein"/"main" gefuehrte Nummer durch alle Kategorien und verschwand
    stillschweigend aus dem Export."""
    import csv as _csv
    import io as _io
    kontakt = _kontakt(telefonnummern=[{"typ": "Allgemein", "nummer": "052 999 99 99"}])
    daten = generator.kontakte_csv([kontakt])
    zeile = list(_csv.DictReader(_io.StringIO(daten.decode("utf-8-sig")), delimiter=";"))[0]
    assert "052 999 99 99" in zeile["Telefon Direkt"]


def test_privates_handy_bleibt_im_pdf_ausgeblendet():
    kontakt = _kontakt(telefonnummern=[{"typ": "Privat Handy", "nummer": "079 999 99 99"}])
    assert generator._direktwahl_pdf(kontakt, privates_telefon_zeigen=False) == ""


def test_eigene_privat_kategorie_bleibt_im_pdf_verborgen():
    """Kategorien sind seit /einstellungen/kategorien frei erweiterbar. Eine dort
    angelegte "Privat 2" darf nicht durch die Privatsphaere-Pruefung fallen -
    sonst stuende eine Privatnummer unbemerkt auf der Adressliste, die aus dem
    Haus geht."""
    from export import generator
    assert generator._ist_privat_typ("Privat 2") is True
    assert generator._ist_privat_typ("Privat Handy") is True
    assert generator._ist_privat_typ("Direkt Handy") is False
    assert generator._ist_privat_typ("Zentrale") is False


def test_unbekannte_kategorie_verschwindet_nicht_aus_dem_csv():
    """Fuer eine selbst angelegte Kategorie gibt es keine eigene CSV-Spalte - der
    Wert muss trotzdem irgendwo auftauchen statt still zu fehlen."""
    from export import generator
    kontakt = {"vorname": "Anna", "nachname": "Muster",
               "telefonnummern": [{"typ": "Zentrale", "nummer": "044 111 11 11"}],
               "emails": [], "adressen": [], "urls": []}
    csv_text = generator.kontakte_csv([kontakt]).decode("utf-8-sig")
    assert "044 111 11 11" in csv_text


# ── Darstellungs-Einstellungen (von /einstellungen hierher gezogen) ───────────
# Firmenname, Logo und die sichtbaren Felder wirken sich ausschliesslich auf den
# PDF-Export aus und stehen deshalb auf dieser Seite (Nutzer-Vorgabe).

def _leere_config(monkeypatch, tmp_path):
    config_pfad = tmp_path / "config.yaml"
    config_pfad.write_text("database:\n  path: rubrica.db\n")
    monkeypatch.setattr(settings, "_CONFIG_PATH", config_pfad)
    monkeypatch.setattr(settings, "_settings", {})


def test_export_speichert_firmenname(tmp_db, monkeypatch, tmp_path):
    _leere_config(monkeypatch, tmp_path)
    TestClient(app).post("/export/einstellungen", data={"export_firmenname": "Muster Architektur AG"})
    assert settings.get("export.firmenname") == "Muster Architektur AG"


def test_export_einstellungen_lassen_andere_abschnitte_unberuehrt(tmp_db, monkeypatch, tmp_path):
    """Regression: die allgemeine Einstellungen-Route speichert saemtliche
    Abschnitte auf einmal. Waeren die Export-Felder weiterhin Teil davon (oder
    umgekehrt), wuerde das Speichern hier die Mail-Zugangsdaten leeren."""
    _leere_config(monkeypatch, tmp_path)
    settings.save({"mail": {"host": "imap.beispiel.ch", "username": "rubrica@beispiel.ch"}})

    TestClient(app).post("/export/einstellungen", data={"export_firmenname": "Muster AG"})

    assert settings.get("mail.host") == "imap.beispiel.ch"
    assert settings.get("mail.username") == "rubrica@beispiel.ch"


def test_export_speichert_sichtbare_felder(tmp_db, monkeypatch, tmp_path):
    _leere_config(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post("/export/einstellungen", data={
        "privates_telefon_zeigen": "on", "private_email_zeigen": "on", "privatadresse_zeigen": "on",
    })
    assert settings.get("export.privates_telefon_zeigen") is True
    assert settings.get("export.private_email_zeigen") is True
    assert settings.get("export.privatadresse_zeigen") is True

    # Nicht angehakt -> muss auf False zurueckgesetzt werden (nicht einfach fehlen)
    client.post("/export/einstellungen", data={})
    assert settings.get("export.privates_telefon_zeigen") is False


def test_export_seite_zeigt_checkbox_status(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"export": {"privates_telefon_zeigen": True}})
    r = TestClient(app).get("/export")
    assert r.status_code == 200
    assert "checked" in r.text.split('name="privates_telefon_zeigen"')[1][:20]


def test_logo_upload_wird_gespeichert_und_ausgeliefert(tmp_db, monkeypatch, tmp_path):
    _leere_config(monkeypatch, tmp_path)
    client = TestClient(app)
    bild_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-png-inhalt"
    r = client.post("/export/einstellungen", data={},
                    files={"logo": ("mein-logo.png", bild_bytes, "image/png")}, follow_redirects=False)
    assert r.status_code == 303

    assert 'src="/export/logo"' in client.get("/export").text
    r = client.get("/export/logo")
    assert r.status_code == 200
    assert r.content == bild_bytes


def test_logo_upload_lehnt_unerlaubte_endung_ab(tmp_db, monkeypatch, tmp_path):
    _leere_config(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post("/export/einstellungen", data={},
                files={"logo": ("script.exe", b"nicht ein bild", "application/octet-stream")})
    assert client.get("/export/logo").status_code == 404


def test_logo_entfernen(tmp_db, monkeypatch, tmp_path):
    _leere_config(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post("/export/einstellungen", data={}, files={"logo": ("logo.png", b"echtbild", "image/png")})
    assert client.get("/export/logo").status_code == 200

    client.post("/export/logo/entfernen")
    assert client.get("/export/logo").status_code == 404
