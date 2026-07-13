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
    assert "TEL;TYPE=MOBIL:079 123 45 67" in vcard
    assert "EMAIL;TYPE=ARBEIT:anna@example.com" in vcard
    assert "ADR;TYPE=ARBEIT:;;Teststrasse 1;Zuerich;ZH;8000;Schweiz" in vcard
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

    assert len(empfangen) == 1
    body = empfangen[0].content
    assert f"kontakt-{k1}".encode() in body
    assert f"kontakt-{k2}".encode() in body


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


def test_tls_verify_ohne_lokale_ca_ist_false(tmp_db, monkeypatch):
    # verify_ssl=True, aber keine lokale CA-Datei vorhanden -> auf Loopback ohne
    # Pruefung, statt den Push mit einem Zertifikatsfehler still scheitern zu lassen.
    monkeypatch.setattr(settings, "_settings", {"radicale": {"verify_ssl": True}})
    assert radicale._tls_verify() is False


def test_tls_verify_nutzt_lokale_ca_wenn_vorhanden(tmp_db, monkeypatch):
    tls_dir = settings.daten_verzeichnis() / "radicale-tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    (tls_dir / "ca-cert.pem").write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(settings, "_settings", {"radicale": {"verify_ssl": True}})
    assert radicale._tls_verify() == str(tls_dir / "ca-cert.pem")


def test_tls_verify_false_wenn_ausdruecklich_deaktiviert(tmp_db, monkeypatch):
    tls_dir = settings.daten_verzeichnis() / "radicale-tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    (tls_dir / "ca-cert.pem").write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(settings, "_settings", {"radicale": {"verify_ssl": False}})
    assert radicale._tls_verify() is False


def test_sync_alle_ohne_konfiguration_meldet_inaktiv(tmp_db, monkeypatch):
    monkeypatch.setattr(radicale, "_client", lambda: None)
    ergebnis = radicale.sync_alle(tmp_db)
    assert ergebnis["aktiv"] is False


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

    def mock_client():
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
