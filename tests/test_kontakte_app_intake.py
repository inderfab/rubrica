import httpx

import kontakte_app_intake
from config import settings
from db import queries
from sync import radicale

_FREMDE_VCARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:ABC-123-FREMD\r\n"
    "FN:Max Mustermann\r\n"
    "N:Mustermann;Max;;;\r\n"
    "EMAIL;TYPE=INTERNET:max@example.com\r\n"
    "END:VCARD\r\n"
)

_FREMDE_GRUPPEN_VCARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:GRUPPE-1-FREMD\r\n"
    "FN:Neue Liste\r\n"
    "N:Neue Liste;;;;\r\n"
    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
    "END:VCARD\r\n"
)


def _propfind_xml(namen: list[str]) -> str:
    hrefs = "".join(f"<response><href>/rubrica/kontakte/{n}</href></response>" for n in namen)
    return f"<multistatus>{hrefs}</multistatus>"


def test_konfiguriert_spiegelt_base_url(monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": ""}})
    assert kontakte_app_intake.konfiguriert() is False
    monkeypatch.setattr(settings, "_settings", {"radicale": {"base_url": "https://127.0.0.1:8443"}})
    assert kontakte_app_intake.konfiguriert() is True


def test_ohne_radicale_konfiguration_meldet_inaktiv(tmp_db, monkeypatch):
    monkeypatch.setattr(radicale, "_client", lambda: None)
    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    assert ergebnis == {"aktiv": False, "geprueft": 0, "neu": 0, "fehler": 0}


def test_erkennt_fremde_vcard_als_vorschlag(tmp_db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["kontakt-1.vcf", "ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis == {"aktiv": True, "geprueft": 1, "neu": 1, "fehler": 0}
    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert len(vorschlaege) == 1
    v = vorschlaege[0]
    assert v["rohdaten"]["vorname"] == "Max"
    assert v["rohdaten"]["nachname"] == "Mustermann"
    assert v["rohdaten"]["kontakte_app_vcf_name"] == "ABC-123-FREMD.vcf"
    assert v["message_id"] == "kontakte-app:ABC-123-FREMD.vcf"
    assert v["status"] == "offen"
    # Rubricas eigene kontakt-1.vcf darf nie als Vorschlag landen.
    assert not any(vv["rohdaten"].get("kontakte_app_vcf_name") == "kontakt-1.vcf" for vv in vorschlaege)


def test_ignoriert_fremde_gruppen_neuanlage(tmp_db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["GRUPPE-1-FREMD.vcf"]))
        if request.url.path == "/a/GRUPPE-1-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_GRUPPEN_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    ergebnis = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert ergebnis["neu"] == 0
    assert queries.list_vorschlaege(tmp_db, quelle="kontakte_app") == []


def test_erkennt_ordner_mitgliedschaft_aus_eigener_projekt_vcard(tmp_db, monkeypatch):
    projekt_id = queries.get_or_create_projekt(tmp_db, "Baustelle Muster")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        if request.url.path == f"/a/projekt-{projekt_id}.vcf":
            return httpx.Response(
                200,
                text=(
                    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:projekt-{0}\r\nFN:Baustelle Muster\r\n"
                    "X-ADDRESSBOOKSERVER-KIND:group\r\n"
                    "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:ABC-123-FREMD\r\nEND:VCARD\r\n"
                ).format(projekt_id),
            )
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert len(vorschlaege) == 1
    assert vorschlaege[0]["rohdaten"]["erkannte_ordner_ids"] == [projekt_id]


def test_dedup_ueber_message_id_verhindert_erneuten_vorschlag(tmp_db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    erster_lauf = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)
    zweiter_lauf = kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    assert erster_lauf["neu"] == 1
    assert zweiter_lauf["geprueft"] == 0
    assert zweiter_lauf["neu"] == 0
    assert len(queries.list_vorschlaege(tmp_db, quelle="kontakte_app")) == 1


def test_erkennt_moeglichen_duplikat_treffer_ueber_email(tmp_db, monkeypatch):
    bestehender_id = queries.create_kontakt(tmp_db, {
        "vorname": "Max", "nachname": "Mustermann",
        "emails": [{"typ": "Direkt", "email": "max@example.com"}],
    })

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    kontakte_app_intake.pruefe_kontakte_app_neuzugaenge(tmp_db)

    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="kontakte_app")
    assert vorschlaege[0]["kontakt_id"] == bestehender_id


def test_pruefe_und_beschreibe_ohne_konfiguration(tmp_db, monkeypatch):
    monkeypatch.setattr(radicale, "_client", lambda: None)
    text = kontakte_app_intake.pruefe_und_beschreibe(tmp_db)
    assert "Kein Radicale-Server konfiguriert" in text


def test_pruefe_und_beschreibe_fasst_ergebnis_zusammen(tmp_db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text=_propfind_xml(["ABC-123-FREMD.vcf"]))
        if request.url.path == "/a/ABC-123-FREMD.vcf":
            return httpx.Response(200, text=_FREMDE_VCARD)
        return httpx.Response(404)

    monkeypatch.setattr(radicale, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://test/a/"
    ))

    text = kontakte_app_intake.pruefe_und_beschreibe(tmp_db)
    assert "1 neue Kontakte.app-Einträge geprüft" in text
    assert "1 neue Kontaktvorschläge angelegt" in text
