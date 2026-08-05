import httpx
from fastapi.testclient import TestClient

from db import queries
from sync import radicale
from web.main import app


def _client():
    return TestClient(app)


def _vollstaendig(**felder) -> dict:
    """Vorschlag mit allen Pflichtfeldern - seit der Pflichtfeldpruefung beim direkten
    Uebernehmen (web/vorschlaege.py) muessen Fixtures, die uebernommen werden sollen,
    vollstaendig sein."""
    daten = {
        "vorname": "Anna", "nachname": "Muster", "kategorie": "Architektin",
        "telefonnummern": [{"typ": "Direkt", "nummer": "044 111 11 11"}],
        "emails": [{"typ": "Direkt", "email": "anna@beispiel.ch"}],
        "adressen": [{"typ": "arbeit", "strasse": "Musterstrasse 1", "plz": "8000",
                      "ort": "Zürich", "region": "", "land": ""}],
    }
    daten.update(felder)
    return daten


def test_seite_zeigt_offene_mail_und_kontakte_app_vorschlaege(tmp_db):
    queries.create_vorschlag(tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []},
                              quelle="mail")
    queries.create_vorschlag(tmp_db, {"vorname": "Chris", "nachname": "Contact", "telefonnummern": [], "emails": []},
                              quelle="kontakte_app")
    queries.create_vorschlag(tmp_db, {"vorname": "Bruno", "nachname": "Beispiel", "telefonnummern": [], "emails": []},
                              quelle="import")

    r = _client().get("/vorschlaege")
    assert r.status_code == 200
    assert "Anna" in r.text
    assert "Chris" in r.text
    assert "Bruno" not in r.text


def test_uebernehmen_legt_kontakt_an_und_schliesst_vorschlag(tmp_db):
    projekt_id = queries.get_or_create_projekt(tmp_db, "Testprojekt")
    vorschlag_id = queries.create_vorschlag(
        tmp_db, _vollstaendig(erkannte_ordner_ids=[projekt_id]), quelle="mail",
    )

    r = _client().post(f"/vorschlaege/{vorschlag_id}/uebernehmen", follow_redirects=False)
    assert r.status_code == 303

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert kontakte[0]["nachname"] == "Muster"
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []


def test_ablehnen_legt_keinen_kontakt_an(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )

    r = _client().post(f"/vorschlaege/{vorschlag_id}/ablehnen", follow_redirects=False)
    assert r.status_code == 303

    assert queries.list_kontakte(tmp_db) == []
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []
    assert queries.get_vorschlag(tmp_db, vorschlag_id)["status"] == "abgelehnt"


def test_bearbeiten_flyover_zeigt_formular_mit_vorbefuellten_werten(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().get(f"/vorschlaege/{vorschlag_id}/bearbeiten-flyover")
    assert r.status_code == 200
    assert 'value="Anna"' in r.text
    assert 'value="Muster"' in r.text


def test_bearbeiten_flyover_unbekannter_vorschlag_ist_404(tmp_db):
    r = _client().get("/vorschlaege/999999/bearbeiten-flyover")
    assert r.status_code == 404


def test_uebernehmen_bearbeitet_speichert_korrigierte_werte(tmp_db):
    projekt_id = queries.get_or_create_projekt(tmp_db, "Testprojekt")
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().post(f"/vorschlaege/{vorschlag_id}/uebernehmen-bearbeitet", data={
        "vorname": "Anna", "nachname": "Korrigiert", "firma": "", "kategorie": "Geologe", "rolle": "",
        "telefon_typ": "Direkt", "telefon_nummer": "079 111 22 33",
        "email_typ": "Direkt", "email_adresse": "anna@beispiel.ch",
        "adresse_typ": "arbeit", "adresse_strasse": "Musterstrasse 1", "adresse_plz": "8000", "adresse_ort": "Zürich",
        "adresse_region": "", "adresse_land": "", "ordner_ids": str(projekt_id),
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/vorschlaege"

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert kontakte[0]["nachname"] == "Korrigiert"
    assert queries.list_vorschlaege(tmp_db, status="offen", quelle="mail") == []


def test_moeglicher_duplikat_zeigt_bestaetigungs_abfrage(tmp_db):
    # Regression: Nutzer-Feedback - beim Uebernehmen eines Mail-Vorschlags mit
    # bereits bekanntem Namen (aber anderer Mailadresse) kam keine Rueckfrage, im
    # Gegensatz zur manuellen Kontakt-Neuanlage. finde_match() erkennt den
    # Duplikat-Kandidaten selbst schon korrekt (siehe kontakt_id auf dem Vorschlag) -
    # es fehlte nur die sichtbare Warnung + Bestaetigung vor dem Zusammenfuehren.
    bestehender_id = queries.create_kontakt(tmp_db, {"vorname": "Bruno", "nachname": "Beispiel"})
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Bruno", "nachname": "Beispiel", "telefonnummern": [],
                 "emails": [{"typ": "Direkt", "email": "neu@beispiel.ch"}]},
        kontakt_id=bestehender_id, quelle="mail",
    )

    r = _client().get("/vorschlaege")
    assert r.status_code == 200
    assert "Möglicher Duplikat" in r.text
    assert "confirm(" in r.text
    assert f"/vorschlaege/{vorschlag_id}/uebernehmen" in r.text
    assert f"/kontakte/{bestehender_id}/bearbeiten" in r.text


def test_ohne_duplikat_keine_bestaetigungs_abfrage(tmp_db):
    queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []}, quelle="mail",
    )
    r = _client().get("/vorschlaege")
    assert r.status_code == 200
    assert "Möglicher Duplikat" not in r.text


def test_jetzt_pruefen_route_kombiniert_beide_quellen(tmp_db, monkeypatch):
    import kontakte_app_intake
    import mail_intake
    monkeypatch.setattr(mail_intake, "pruefe_und_beschreibe",
                         lambda conn: "3 Nachrichten geprüft, 1 neue Kontaktvorschläge angelegt.")
    monkeypatch.setattr(kontakte_app_intake, "pruefe_und_beschreibe",
                         lambda conn: "2 neue Kontakte.app-Einträge geprüft, 1 neue Kontaktvorschläge angelegt.")

    r = _client().post("/vorschlaege/pruefen", follow_redirects=False)
    assert r.status_code == 303
    assert "meldung=" in r.headers["location"]

    r2 = _client().get(r.headers["location"])
    assert "3 Nachrichten geprüft" in r2.text
    assert "2 neue Kontakte.app-Einträge geprüft" in r2.text


def test_uebernehmen_weist_erkannte_ordner_zu_und_loescht_fremde_vcard(tmp_db, monkeypatch):
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle Muster")
    vorschlag_id = queries.create_vorschlag(
        tmp_db, _vollstaendig(vorname="Chris", nachname="Contact",
                              erkannte_ordner_ids=[projekt_id],
                              kontakte_app_vcf_name="ABC-123-FREMD.vcf"),
        quelle="kontakte_app",
    )

    geloescht = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            geloescht.append(request.url.path)
            return httpx.Response(204)
        return httpx.Response(201)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    r = _client().post(f"/vorschlaege/{vorschlag_id}/uebernehmen", follow_redirects=False)
    assert r.status_code == 303

    kontakte = queries.list_kontakte(tmp_db)
    assert len(kontakte) == 1
    assert [p["id"] for p in kontakte[0]["projekte"]] == [projekt_id]
    assert "/a/ABC-123-FREMD.vcf" in geloescht


def test_seite_zeigt_ordner_vorschlag(tmp_db):
    queries.create_vorschlag(tmp_db, {
        "typ": "ordner", "name": "Neue Liste", "apple_gruppe_uid": "GRUPPE-1",
        "mitglieder_uids": ["A", "B"], "kontakte_app_vcf_name": "GRUPPE-1.vcf",
    }, quelle="kontakte_app")

    r = _client().get("/vorschlaege")
    assert r.status_code == 200
    assert "Neue Liste" in r.text
    assert "2 Mitglied(er) erkannt" in r.text


def test_uebernehmen_ordner_vorschlag_legt_ordner_an_und_loescht_fremde_vcard(tmp_db, monkeypatch):
    bekannter_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster",
                                                     "apple_uid": "ANNA-UID"})
    vorschlag_id = queries.create_vorschlag(tmp_db, {
        "typ": "ordner", "name": "Neue Liste", "apple_gruppe_uid": "GRUPPE-1",
        "mitglieder_uids": ["ANNA-UID"], "kontakte_app_vcf_name": "GRUPPE-1.vcf",
    }, quelle="kontakte_app")

    geloescht = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            geloescht.append(request.url.path)
            return httpx.Response(204)
        return httpx.Response(201)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    r = _client().post(f"/vorschlaege/{vorschlag_id}/uebernehmen", follow_redirects=False)
    assert r.status_code == 303

    ordner = queries.list_projekte(tmp_db)
    assert any(o["name"] == "Neue Liste" for o in ordner)
    kontakt = queries.get_kontakt(tmp_db, bekannter_id)
    assert len(kontakt["projekte"]) == 1
    assert "/a/GRUPPE-1.vcf" in geloescht
    assert queries.get_vorschlag(tmp_db, vorschlag_id)["status"] == "bestaetigt"


def test_ablehnen_entfernt_fremde_vcard_aus_dem_adressbuch(tmp_db, monkeypatch):
    """Regression (Nutzer-Meldung): ein abgelehnter Kontakte.app-Vorschlag blieb als
    Karteileiche im gemeinsamen Adressbuch liegen - auf allen Geraeten sichtbar, von
    Rubrica nicht verwaltet und nie wieder angeboten, weil der Dublettenschutz nur
    nach der message_id fragt und den Status ignoriert."""
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Chris", "nachname": "Contact", "telefonnummern": [], "emails": [],
                 "kontakte_app_vcf_name": "ABC-123-FREMD.vcf"},
        quelle="kontakte_app", message_id="kontakte-app:ABC-123-FREMD.vcf",
    )

    geloescht = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            geloescht.append(request.url.path)
            return httpx.Response(204)
        return httpx.Response(201)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    r = _client().post(f"/vorschlaege/{vorschlag_id}/ablehnen", follow_redirects=False)
    assert r.status_code == 303
    assert "/a/ABC-123-FREMD.vcf" in geloescht
    assert queries.get_vorschlag(tmp_db, vorschlag_id)["status"] == "abgelehnt"
    assert queries.list_kontakte(tmp_db) == []


def test_ablehnen_entfernt_abgelehnten_ordner_aus_dem_adressbuch(tmp_db, monkeypatch):
    vorschlag_id = queries.create_vorschlag(tmp_db, {
        "typ": "ordner", "name": "Neue Liste", "apple_gruppe_uid": "GRUPPE-1",
        "mitglieder_uids": [], "kontakte_app_vcf_name": "GRUPPE-1.vcf",
    }, quelle="kontakte_app", message_id="kontakte-app:GRUPPE-1.vcf")

    geloescht = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            geloescht.append(request.url.path)
            return httpx.Response(204)
        return httpx.Response(201)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    _client().post(f"/vorschlaege/{vorschlag_id}/ablehnen", follow_redirects=False)

    assert "/a/GRUPPE-1.vcf" in geloescht
    assert queries.list_projekte(tmp_db) == []


def test_ablehnen_eines_mail_vorschlags_loescht_nichts_auf_radicale(tmp_db, monkeypatch):
    """Mail-Vorschlaege haben keine vCard auf Radicale - hier darf nie eine
    Loeschanfrage rausgehen (sonst wuerde ein zufaellig gleich benannter Eintrag
    getroffen)."""
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []},
        quelle="mail", message_id="<abc@example.com>",
    )

    anfragen = []

    def handler(request: httpx.Request) -> httpx.Response:
        anfragen.append(request.method)
        return httpx.Response(204)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    _client().post(f"/vorschlaege/{vorschlag_id}/ablehnen", follow_redirects=False)

    assert anfragen == []
    assert queries.get_vorschlag(tmp_db, vorschlag_id)["status"] == "abgelehnt"


def test_ablehnen_rueckfrage_nennt_die_folge_nur_bei_kontakte_app(tmp_db):
    """Das Loeschen auf allen Geraeten darf keine Ueberraschung sein - bei
    Mail-Vorschlaegen waere derselbe Hinweis dagegen schlicht falsch."""
    queries.create_vorschlag(
        tmp_db, {"vorname": "Chris", "nachname": "Contact", "telefonnummern": [], "emails": [],
                 "kontakte_app_vcf_name": "ABC.vcf"}, quelle="kontakte_app")
    queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster", "telefonnummern": [], "emails": []},
        quelle="mail")

    text = _client().get("/vorschlaege").text
    assert text.count("auch in Kontakte.app auf allen Geräten entfernt") == 1


def test_unvollstaendiger_vorschlag_wird_nicht_direkt_uebernommen(tmp_db):
    """Aus Kontakte.app kommen Kontakte praktisch nie mit Funktion und Ordner. Der
    direkte Weg pruefte das bisher nicht - nur der Bearbeiten-Weg. So landeten
    unvollstaendige Kontakte im Bestand."""
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Chris", "nachname": "Contact", "telefonnummern": [], "emails": [],
                 "kontakte_app_vcf_name": "ABC.vcf"}, quelle="kontakte_app")

    r = _client().post(f"/vorschlaege/{vorschlag_id}/uebernehmen", follow_redirects=False)

    assert r.status_code == 303
    assert "meldung=" in r.headers["location"]
    assert queries.list_kontakte(tmp_db) == []
    assert queries.get_vorschlag(tmp_db, vorschlag_id)["status"] == "offen"
    r2 = _client().get(r.headers["location"])
    assert "Funktion" in r2.text and "Ordner" in r2.text


def test_loeschvorschlag_uebernehmen_loescht_den_kontakt(tmp_db, monkeypatch):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"typ": "loeschung", "vorname": "Anna", "nachname": "Muster", "firma": ""},
        kontakt_id=kontakt_id, quelle="kontakte_app",
        message_id=f"kontakte-app-loeschung:{kontakt_id}")

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(204)), base_url="https://test/a/"))

    _client().post(f"/vorschlaege/{vorschlag_id}/uebernehmen", follow_redirects=False)

    assert queries.get_kontakt(tmp_db, kontakt_id) is None


def test_loeschvorschlag_behalten_stellt_wieder_her(tmp_db, monkeypatch):
    """Reihenfolge-Regression: solange der Loeschvorschlag offen ist, unterdrueckt
    push_kontakt jeden Push. Wird der Status nicht VOR dem Push gesetzt, wird die
    Wiederherstellung still verschluckt und der Kontakt bleibt auf den Geraeten weg."""
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Anna", "nachname": "Muster"})
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"typ": "loeschung", "vorname": "Anna", "nachname": "Muster", "firma": ""},
        kontakt_id=kontakt_id, quelle="kontakte_app",
        message_id=f"kontakte-app-loeschung:{kontakt_id}")

    gesendet = []

    def handler(request):
        gesendet.append((request.method, request.url.path))
        return httpx.Response(201)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"))

    _client().post(f"/vorschlaege/{vorschlag_id}/ablehnen", follow_redirects=False)

    assert queries.get_kontakt(tmp_db, kontakt_id) is not None
    assert ("PUT", f"/a/kontakt-{kontakt_id}.vcf") in gesendet
