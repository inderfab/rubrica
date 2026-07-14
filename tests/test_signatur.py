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
    assert {"typ": "Direkt", "email": "anna.braendli@strut.ch"} in d["emails"]
    assert any(u["url"] == "www.strut.ch" for u in d["urls"])
    # E-Mail-Domain darf nicht als URL auftauchen
    assert not any("@" in u["url"] for u in d["urls"])


def test_telefon_klassifikation():
    d = parse_signatur(SIG_TYPISCH)
    typen = {t["typ"]: t["nummer"] for t in d["telefonnummern"]}
    assert "Direkt" in typen and "52" in typen["Direkt"]
    assert "Privat" in typen and "79" in typen["Privat"]


def test_firma_und_name():
    d = parse_signatur(SIG_TYPISCH)
    assert d["firma"] == "Strut Architekten AG"
    assert d["vorname"] == "Anna"
    assert d["nachname"] == "Brändli"


def test_literale_br_tags_werden_als_zeilenumbruch_behandelt():
    # Realer Fund: manche Quell-Mails sind eigentlich HTML, dessen Umbrueche als
    # woertliche "<br>"-Tags im Text landen - ohne Behandlung haengt der Tag am
    # Namen und verunstaltet ihn ("Marcel Müllhaupt<br>").
    text = "Freundliche Gruesse<br>Marcel Müllhaupt<br>Architekt FH<br>Strut Architekten AG"
    d = parse_signatur(text)
    assert d["vorname"] == "Marcel"
    assert d["nachname"] == "Müllhaupt"


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
    assert "Privat" in typen  # 079... als Mobil -> gilt als privat
    assert "Direkt" in typen  # 044... als Festnetz


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
    assert typen == {"Direkt", "Allgemein", "Privat"}
    assert d["firma"] == "GeoTest AG"
    assert d["emails"][0]["email"] == "hans.meier@geotest.ch"


def test_lange_tracking_links_werden_ignoriert():
    """SharePoint/OneDrive-Freigabelinks (kodierte Query-Strings, oft >100 Zeichen)
    sollen nicht als Homepage uebernommen werden - gefunden bei Haertung an echten
    (anonymisiert analysierten) E-Mail-Signaturen."""
    tracking_link = "https://firma-my.sharepoint.com/personal/x/_layouts/15/onedrive.aspx" + "?id=" + "a" * 150
    sig = f"Max Muster\nMuster AG\nwww.muster.ch\n{tracking_link}"
    d = parse_signatur(sig)
    urls = [u["url"] for u in d["urls"]]
    assert "www.muster.ch" in urls
    assert not any(len(u) > 120 for u in urls)


def test_kurze_url_bleibt_erhalten():
    d = parse_signatur("Max Muster\nhttps://muster.ch/team")
    assert d["urls"][0]["url"] == "https://muster.ch/team"


def test_funktionszeile_wird_nicht_als_name_uebernommen():
    d = parse_signatur("Dipl. Ing. Arch.\nATELIER NU AG FH ETH SIA\n043 543 23 50\nschoett@atelier-nu.ch")
    assert d["vorname"] == "" and d["nachname"] == ""


def test_newsletter_absatz_wird_nicht_als_firma_uebernommen():
    absatz = ("Sie erhalten diese E-Mail, weil Sie bei uns als Kunde hinterlegt und als "
              "Newsletter-Abonnent eingetragen sind. Um Sie ueber die Neuigkeiten der Sennrich AG "
              "zu informieren, senden wir Ihnen diesen Newsletter.")
    d = parse_signatur(absatz + "\n072462070")
    assert d["firma"] == ""


def test_unplausible_telefonnummer_wird_verworfen():
    # "011 8544 000" saehe wie eine Nummer aus, ist aber keine gueltige CH-Vorwahl
    # (zweite Ziffer nach der 0 darf nicht 0 oder 1 sein).
    d = parse_signatur("Enerpeak AG\n011 8544 000")
    assert d["telefonnummern"] == []


def test_gueltige_ch_nummern_bleiben_erhalten():
    d = parse_signatur("Muster AG\n+41 52 233 93 93\n044 746 43 43")
    nummern = {t["nummer"] for t in d["telefonnummern"]}
    assert any("52 233 93 93" in n for n in nummern)
    assert any("44 746 43 43" in n for n in nummern)
