import httpx

from config import settings
from db import queries
from sync import radicale


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


def test_kontakt_zu_vcard_enthaelt_alle_felder():
    vcard = radicale.kontakt_zu_vcard(_kontakt())
    assert "UID:kontakt-1" in vcard
    assert "FN:Anna Muster" in vcard
    assert "ORG:Muster AG" in vcard
    assert "TITLE:Bauleiterin" in vcard
    assert "CATEGORIES:Fachplaner" in vcard
    # Telefon und E-Mail tragen die Kategorie als X-ABLabel, nicht als TYPE: unsere
    # Kategorien sind keine vCard-Typen, und "Privat Handy" waere als Parameterwert
    # mit Leerzeichen ungueltig (siehe radicale._beschriftete_zeilen).
    assert "item1.TEL;TYPE=WORK;TYPE=CELL:079 123 45 67" in vcard
    assert "item1.X-ABLabel:mobil" in vcard
    assert "item2.EMAIL;TYPE=WORK:anna@example.com" in vcard
    assert "item2.X-ABLabel:arbeit" in vcard
    assert "item3.ADR;TYPE=WORK:;;Teststrasse 1;Zuerich;ZH;8000;Schweiz" in vcard
    assert "item3.X-ABLabel:arbeit" in vcard
    assert "URL;TYPE=HOMEPAGE:https://example.com" in vcard
    assert "NOTE:Testnotiz" in vcard


def test_kontakt_zu_vcard_escaped_sonderzeichen():
    vcard = radicale.kontakt_zu_vcard(_kontakt(
        vorname="A;B", nachname="C,D", firma="", rolle="", kategorie="",
        notizen="Zeile1\nZeile2", telefonnummern=[], emails=[], adressen=[], urls=[],
    ))
    assert "A\\;B" in vcard
    assert "C\\,D" in vcard
    assert "Zeile1\\nZeile2" in vcard


def test_kontakt_zu_vcard_faltet_lange_zeilen():
    lange_notiz = "Ein sehr langer Notiztext, " * 10  # deutlich ueber 75 Oktette
    vcard = radicale.kontakt_zu_vcard(_kontakt(notizen=lange_notiz, telefonnummern=[], emails=[], adressen=[], urls=[]))
    zeilen = vcard.split("\r\n")
    # Jede physische Zeile (bis auf Fortsetzungen, die mit einem Leerzeichen beginnen)
    # darf 75 Oktette nicht ueberschreiten.
    for z in zeilen:
        if z.startswith(" "):
            continue
        assert len(z.encode("utf-8")) <= 75, f"Zeile zu lang: {len(z.encode('utf-8'))} Oktette"
    # Der komplette Notiztext muss trotz Faltung wieder zusammensetzbar sein.
    wieder_zusammengesetzt = vcard.replace("\r\n ", "")
    assert lange_notiz.replace(",", "\\,") in wieder_zusammengesetzt


def test_fold_teilt_nicht_mitten_in_utf8_zeichen():
    # Umlaute sind in UTF-8 mehrere Bytes - die Faltung darf sie nicht zerreissen.
    text = "Straße " * 15
    gefaltet = radicale._fold(f"NOTE:{text}")
    wieder_zusammengesetzt = gefaltet.replace("\r\n ", "")
    assert wieder_zusammengesetzt == f"NOTE:{text}"


def test_projekt_zu_gruppen_vcard():
    vcard = radicale.projekt_zu_gruppen_vcard({"id": 5, "name": "Testprojekt"}, [1, 2])
    assert "UID:projekt-5" in vcard
    assert "FN:Testprojekt" in vcard
    assert "X-ADDRESSBOOKSERVER-KIND:group" in vcard
    assert "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:kontakt-1" in vcard
    assert "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:kontakt-2" in vcard


def test_push_kontakt_sendet_put_mit_korrektem_pfad_und_inhalt(tmp_db, monkeypatch):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})

    empfangen = []

    def handler(request: httpx.Request) -> httpx.Response:
        empfangen.append(request)
        return httpx.Response(201)

    mock_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test/addressbook/")
    monkeypatch.setattr(radicale, "_client", lambda: mock_client)

    radicale.push_kontakt(tmp_db, kontakt_id)

    assert len(empfangen) == 1
    req = empfangen[0]
    assert req.method == "PUT"
    assert req.url.path == f"/addressbook/kontakt-{kontakt_id}.vcf"
    assert b"FN:Anna Muster" in req.content


def test_push_projekt_sendet_mitgliederliste(tmp_db, monkeypatch):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Testprojekt")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])
    queries.set_kontakt_projekte(tmp_db, k2, [projekt_id])

    empfangen = []

    def handler(request: httpx.Request) -> httpx.Response:
        empfangen.append(request)
        return httpx.Response(201)

    mock_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test/addressbook/")
    monkeypatch.setattr(radicale, "_client", lambda: mock_client)

    radicale.push_projekt(tmp_db, projekt_id)

    # Lesen vor Schreiben: erst den Serverstand holen (Mitglieder eines Kollegen und
    # noch offene Kontakte.app-Karten), dann schreiben.
    assert [r.method for r in empfangen] == ["GET", "PUT"]
    body = empfangen[-1].content
    assert f"kontakt-{k1}".encode() in body
    assert f"kontakt-{k2}".encode() in body


def test_push_projekt_loescht_statt_pusht_bei_z_ordner(tmp_db, monkeypatch):
    """Z-Ordner (z.B. "Z1_Weihnachten 2013") werden nie als Apple-Gruppe
    synchronisiert - siehe radicale._ist_z_ordner (Nutzer-Vorgabe). push_projekt()
    sendet dafuer aktiv ein DELETE statt nur zu ueberspringen (siehe
    test_push_projekt_ordner_umbenannt_ins_archiv_entfernt_alte_vcard_sofort fuer den
    Regressionsgrund) - ein 404 auf eine nie gepushte vCard gilt in _delete() bereits
    als Erfolg, daher hier unschaedlich."""
    projekt_id = queries.get_or_create_projekt(tmp_db, "Z1_Archiv")

    empfangen = []

    def handler(request: httpx.Request) -> httpx.Response:
        empfangen.append(request)
        return httpx.Response(404)

    mock_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test/addressbook/")
    monkeypatch.setattr(radicale, "_client", lambda: mock_client)

    ergebnis = radicale.push_projekt(tmp_db, projekt_id)

    assert ergebnis is True
    assert len(empfangen) == 1
    assert empfangen[0].method == "DELETE"
    assert empfangen[0].url.path == f"/addressbook/projekt-{projekt_id}.vcf"


def test_push_projekt_ordner_umbenannt_ins_archiv_entfernt_alte_vcard_sofort(tmp_db, monkeypatch):
    # Regression (Nutzer-Feedback): ein Ordner, der VOR der Umbenennung mit Z-Praefix
    # bereits unter dem alten Namen an Radicale gepusht war, blieb auf den
    # synchronisierten Geraeten sichtbar - push_projekt() gab bei einem Z-Ordner bisher
    # nur "True" zurueck, ohne die alte vCard tatsaechlich zu entfernen.
    projekt_id = queries.get_or_create_projekt(tmp_db, "Weihnachtsessen 2013")

    empfangen = []

    def handler(request: httpx.Request) -> httpx.Response:
        empfangen.append((request.method, request.url.path))
        return httpx.Response(201 if request.method == "PUT" else 204)

    mock_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test/addressbook/")
    monkeypatch.setattr(radicale, "_client", lambda: mock_client)

    # Zuerst normal gepusht (wie vor der Umbenennung).
    radicale.push_projekt(tmp_db, projekt_id, client=mock_client)
    assert ("PUT", f"/addressbook/projekt-{projekt_id}.vcf") in empfangen

    # Jetzt umbenennen (Nutzer-Aktion: Ordner mit Z-Praefix ins Archiv verschieben).
    queries.rename_projekt(tmp_db, projekt_id, "Z1_Weihnachtsessen 2013")
    empfangen.clear()
    ergebnis = radicale.push_projekt(tmp_db, projekt_id, client=mock_client)

    assert ergebnis is True
    assert ("DELETE", f"/addressbook/projekt-{projekt_id}.vcf") in empfangen


def test_delete_projekt_sendet_delete(monkeypatch):
    empfangen = []

    def handler(request: httpx.Request) -> httpx.Response:
        empfangen.append(request)
        return httpx.Response(204)

    mock_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test/addressbook/")
    monkeypatch.setattr(radicale, "_client", lambda: mock_client)

    radicale.delete_projekt(3)

    assert len(empfangen) == 1
    assert empfangen[0].method == "DELETE"
    assert empfangen[0].url.path == "/addressbook/projekt-3.vcf"


def test_sync_deaktiviert_macht_nichts_und_wirft_nicht(tmp_db, monkeypatch):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel"})
    monkeypatch.setattr(radicale, "_client", lambda: None)

    radicale.push_kontakt(tmp_db, kontakt_id)
    radicale.delete_kontakt(kontakt_id)


def test_client_ist_ohne_base_url_none(monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": ""}})
    assert radicale._client() is None


def test_client_braucht_keinen_enabled_schalter(monkeypatch):
    # Kein "enabled"-Feld gesetzt - Sync muss trotzdem aktiv sein, sobald eine
    # base_url konfiguriert ist (siehe _client()-Docstring: kein An/Aus-Schalter mehr,
    # da ein versehentlich falsch gesetzter Schalter schon zu Verwirrung gefuehrt hat).
    monkeypatch.setattr(settings, "_settings", {
        "radicale": {"base_url": "https://127.0.0.1:8443", "addressbook_path": "/pas/kontakte/"}
    })
    client = radicale._client()
    assert client is not None
    client.close()


def test_client_prueft_tls_nicht_auf_loopback(monkeypatch):
    # Der Push geht an das eigene Radicale auf 127.0.0.1 - TLS-Pruefung ist dort
    # bewusst aus (verify=False), weil das lokale Zertifikat sonst wiederholt zu
    # stillen Push-Fehlern fuehrte (certifi-unbekannte CA / SAN ohne 127.0.0.1).
    monkeypatch.setattr(settings, "_settings", {
        "radicale": {"base_url": "https://127.0.0.1:8443", "addressbook_path": "/pas/kontakte/"}
    })
    client = radicale._client()
    assert client is not None
    # httpx speichert die Verify-Einstellung nicht oeffentlich zugaenglich; wir
    # pruefen stattdessen, dass _client ueberhaupt einen Client baut (TLS-Details
    # sind in _client hart auf verify=False gesetzt).
    client.close()


def test_sync_alle_ohne_konfiguration_meldet_inaktiv(tmp_db, monkeypatch):
    monkeypatch.setattr(radicale, "_client", lambda: None)
    ergebnis = radicale.sync_alle(tmp_db)
    assert ergebnis["aktiv"] is False


def test_client_verwendet_immer_den_fest_verdrahteten_benutzer(monkeypatch):
    # RADICALE_BENUTZER ist bewusst nicht konfigurierbar (siehe sync/radicale.py) -
    # selbst wenn config.yaml (z.B. aus einer alten Installation) noch einen
    # abweichenden username/addressbook_path enthaelt, muss Rubrica trotzdem immer
    # gegen den fest verdrahteten Benutzer pushen. Verhindert den bereits
    # aufgetretenen owner_only-Mismatch.
    monkeypatch.setattr(settings, "_settings", {
        "radicale": {"base_url": "https://127.0.0.1:8443",
                     "username": "contact", "addressbook_path": "/contact/kontakte/"}
    })
    client = radicale._client()
    assert str(client.base_url).endswith(f"/{radicale.RADICALE_BENUTZER}/kontakte/")
    assert client.auth is not None
    client.close()


def test_sync_alle_pusht_alle_und_entfernt_verwaiste(tmp_db, monkeypatch):
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel"})

    gesendet = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesendet.append((request.method, request.url.path))
        if request.method == "PROPFIND":
            # Radicale meldet einen verwaisten Kontakt (kontakt-999), der nicht mehr in der DB ist.
            xml = ('<multistatus><response><href>/a/kontakt-999.vcf</href></response>'
                   f'<response><href>/a/kontakt-{k1}.vcf</href></response></multistatus>')
            return httpx.Response(207, text=xml)
        return httpx.Response(201)

    client_aufrufe = []

    def mock_client():
        client_aufrufe.append(1)
        return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test/a/")

    monkeypatch.setattr(radicale, "_client", mock_client)

    ergebnis = radicale.sync_alle(tmp_db)

    assert ergebnis["aktiv"] is True
    assert ergebnis["kontakte"] == 2
    assert ergebnis["entfernt"] == 1  # kontakt-999 entfernt
    # Der verwaiste Kontakt wurde per DELETE entfernt, die echten per PUT gepusht.
    assert ("DELETE", "/a/kontakt-999.vcf") in gesendet
    assert ("PUT", f"/a/kontakt-{k1}.vcf") in gesendet
    assert ("PUT", f"/a/kontakt-{k2}.vcf") in gesendet
    # Effizienz: der gesamte Voll-Sync nutzt EINE Verbindung, nicht eine pro Datensatz.
    assert len(client_aufrufe) == 1


def test_sync_alle_entfernt_bereits_gepushten_z_ordner(tmp_db, monkeypatch):
    """Ein Z-Ordner, der vor Einfuehrung der Z-Ordner-Regel schon als Apple-Gruppe
    gepusht wurde, wird beim naechsten Voll-Sync als verwaist erkannt und entfernt -
    ohne eigenen Loesch-Code, siehe radicale.sync_alle/_ist_z_ordner."""
    z_projekt_id = queries.get_or_create_projekt(tmp_db, "Z1_Archiv")

    gesendet = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesendet.append((request.method, request.url.path))
        if request.method == "PROPFIND":
            xml = f'<multistatus><response><href>/a/projekt-{z_projekt_id}.vcf</href></response></multistatus>'
            return httpx.Response(207, text=xml)
        return httpx.Response(201)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    ergebnis = radicale.sync_alle(tmp_db)

    assert ergebnis["entfernt"] == 1
    assert ("DELETE", f"/a/projekt-{z_projekt_id}.vcf") in gesendet
    assert ("PUT", f"/a/projekt-{z_projekt_id}.vcf") not in gesendet


def test_kategorie_ueberlebt_den_weg_durch_die_vcard():
    """Regression (Nutzer-Meldung: reihenweise Vorschläge "Privat -> Direkt" für
    Nummern, die niemand angefasst hatte). Die Kategorie stand als TYPE in der
    vCard - "PRIVAT HANDY" ist als Parameterwert mit Leerzeichen ungültig und fand
    beim Zurücklesen keine Zuordnung mehr, landete also auf "Direkt". Da die
    Änderungserkennung geparsten Schnappschuss gegen geparsten Serverstand
    vergleicht, wurde daraus ein Änderungsvorschlag."""
    import vobject
    from importer import vcard as vcard_modul

    kategorien = ["Direkt", "Direkt Handy", "Privat", "Privat Handy", "Sekretariat"]
    kontakt = _kontakt(
        telefonnummern=[{"typ": k, "nummer": f"+41 44 111 11 {i:02d}"} for i, k in enumerate(kategorien)],
        emails=[{"typ": k, "email": f"{i}@beispiel.ch"} for i, k in enumerate(["Direkt", "Allgemein", "Privat"])],
    )
    zurueck = vcard_modul._parse_kontakt(vobject.readOne(radicale.kontakt_zu_vcard(kontakt)))

    assert [t["typ"] for t in zurueck["telefonnummern"]] == kategorien
    assert [e["typ"] for e in zurueck["emails"]] == ["Direkt", "Allgemein", "Privat"]


def test_alte_vcards_mit_kategorie_als_typ_bleiben_lesbar():
    """Karten im alten Format liegen weiterhin auf dem Server - der Rückweg muss
    sie verstehen, sonst meldet die Änderungserkennung sie als Umkategorisierung."""
    import vobject
    from importer import vcard as vcard_modul

    alt = ("BEGIN:VCARD\r\nVERSION:3.0\r\nN:Muster;Anna;;;\r\nFN:Anna Muster\r\n"
           "TEL;TYPE=PRIVAT HANDY:+41 79 242 59 32\r\n"
           "TEL;TYPE=DIREKT HANDY:+41 79 111 11 11\r\n"
           "TEL;TYPE=PRIVAT:+41 44 222 22 22\r\n"
           "END:VCARD\r\n")
    typen = [t["typ"] for t in vcard_modul._parse_kontakt(vobject.readOne(alt))["telefonnummern"]]
    assert typen == ["Privat Handy", "Direkt Handy", "Privat"]


def test_push_projekt_schreibt_nicht_wenn_sich_nichts_geaendert_hat(tmp_db, monkeypatch):
    """Jede Speicherung eines Kontakts pusht alle seine Ordner mit. Schreibt das die
    Mitgliederliste auch dann neu, wenn sie unverändert ist, ist jedes dieser
    überflüssigen Schreiben eine Gelegenheit, eine gerade erst in Kontakte.app
    gesetzte, aber noch nicht hochgeladene Zuordnung zu überschreiben."""
    k1 = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    projekt_id = queries.get_or_create_projekt(tmp_db, "Testprojekt")
    queries.set_kontakt_projekte(tmp_db, k1, [projekt_id])

    server = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            server[request.url.path] = request.content.decode()
            return httpx.Response(201)
        text = server.get(request.url.path)
        return httpx.Response(200, text=text) if text else httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    radicale.push_projekt(tmp_db, projekt_id)
    vorher = server[f"/a/projekt-{projekt_id}.vcf"]

    geschrieben = []
    original_put = radicale._put

    def zaehlendes_put(pfad, vcard, client=None):
        geschrieben.append(pfad)
        return original_put(pfad, vcard, client=client)

    monkeypatch.setattr(radicale, "_put", zaehlendes_put)
    assert radicale.push_projekt(tmp_db, projekt_id) is True
    assert geschrieben == [], "unveränderte Mitgliederliste wurde erneut geschrieben"

    # Aendert sich tatsaechlich etwas, wird selbstverstaendlich geschrieben.
    k2 = queries.create_kontakt(tmp_db, {"vorname": "Bob", "nachname": "Beispiel"})
    queries.set_kontakt_projekte(tmp_db, k2, [projekt_id])
    radicale.push_projekt(tmp_db, projekt_id)
    assert geschrieben == [f"projekt-{projekt_id}.vcf"]
    assert server[f"/a/projekt-{projekt_id}.vcf"] != vorher
