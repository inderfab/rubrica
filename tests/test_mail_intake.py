import textwrap
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase

import mail_intake
from config import settings
from db import queries


def _konfigurieren(monkeypatch):
    monkeypatch.setattr(settings, "_settings", {"mail": {
        "host": "imap.example.com", "port": 993, "username": "rubrica@example.com", "password": "geheim",
    }})


def _vcard_mail(message_id: str, vcard_text: str) -> bytes:
    msg = MIMEMultipart()
    msg["Message-ID"] = message_id
    msg["Subject"] = "Kontakt"
    anhang = MIMEBase("text", "vcard")
    anhang.set_payload(vcard_text)
    anhang.add_header("Content-Disposition", "attachment", filename="kontakt.vcf")
    msg.attach(anhang)
    return msg.as_bytes()


def _text_mail(message_id: str, text: str) -> bytes:
    msg = MIMEText(text, "plain")
    msg["Message-ID"] = message_id
    msg["Subject"] = "Neuer Kontakt"
    return msg.as_bytes()


class _FakeClient:
    def __init__(self, rohnachrichten: dict):
        self._rohnachrichten = rohnachrichten
        self.geloggt_out = False

    def socket(self):
        class _S:
            def settimeout(self, *_a):
                pass
        return _S()

    def login(self, *_a):
        pass

    def select(self, *_a, **_kw):
        return "OK", [b""]

    def search(self, *_a):
        uids = list(self._rohnachrichten.keys())
        return "OK", [b" ".join(uids)]

    def fetch(self, uid, *_a):
        return "OK", [(b"1 (BODY[] {1})", self._rohnachrichten[uid])]

    def logout(self):
        self.geloggt_out = True


VCARD = textwrap.dedent("""\
    BEGIN:VCARD
    VERSION:3.0
    N:Muster;Anna;;;
    FN:Anna Muster
    TEL;TYPE=CELL:+41 79 123 45 67
    END:VCARD
""")


def test_nicht_konfiguriert_liefert_inaktiv(tmp_db):
    monkeypatch_leer = {}
    assert mail_intake.konfiguriert() is False
    ergebnis = mail_intake.pruefe_mail_eingang(tmp_db)
    assert ergebnis == {"aktiv": False, "gefunden": 0, "neu": 0, "fehler": 0}


def test_vcard_anhang_erzeugt_vorschlag(tmp_db, monkeypatch):
    _konfigurieren(monkeypatch)
    fake = _FakeClient({b"1": _vcard_mail("<eins@example.com>", VCARD)})
    monkeypatch.setattr(mail_intake, "_client", lambda: fake)

    ergebnis = mail_intake.pruefe_mail_eingang(tmp_db)

    assert ergebnis == {"aktiv": True, "gefunden": 1, "neu": 1, "fehler": 0}
    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="mail")
    assert len(vorschlaege) == 1
    assert vorschlaege[0]["rohdaten"]["nachname"] == "Muster"
    assert fake.geloggt_out is True


def test_reiner_text_wird_wie_signatur_geparst(tmp_db, monkeypatch):
    _konfigurieren(monkeypatch)
    text = "Bruno Beispiel\nBeispiel AG\n079 111 22 33\nbruno@beispiel.ch"
    fake = _FakeClient({b"1": _text_mail("<zwei@example.com>", text)})
    monkeypatch.setattr(mail_intake, "_client", lambda: fake)

    ergebnis = mail_intake.pruefe_mail_eingang(tmp_db)

    assert ergebnis["neu"] == 1
    vorschlaege = queries.list_vorschlaege(tmp_db, quelle="mail")
    assert vorschlaege[0]["rohdaten"]["emails"][0]["email"] == "bruno@beispiel.ch"


def test_bereits_verarbeitete_message_id_wird_uebersprungen(tmp_db, monkeypatch):
    _konfigurieren(monkeypatch)
    queries.create_vorschlag(tmp_db, {"vorname": "Anna"}, quelle="mail", message_id="<eins@example.com>")
    fake = _FakeClient({b"1": _vcard_mail("<eins@example.com>", VCARD)})
    monkeypatch.setattr(mail_intake, "_client", lambda: fake)

    ergebnis = mail_intake.pruefe_mail_eingang(tmp_db)

    assert ergebnis == {"aktiv": True, "gefunden": 1, "neu": 0, "fehler": 0}
    assert len(queries.list_vorschlaege(tmp_db, quelle="mail")) == 1  # nicht verdoppelt


def test_kaputte_nachricht_zaehlt_als_fehler_bricht_aber_nicht_ab(tmp_db, monkeypatch):
    _konfigurieren(monkeypatch)
    fake = _FakeClient({
        b"1": b"das ist keine gueltige E-Mail-Struktur \xff\xfe",
        b"2": _vcard_mail("<zwei@example.com>", VCARD),
    })

    original = mail_intake._kandidaten_aus_nachricht

    def _kaputter_parser(msg):
        if not msg.get("Message-ID"):
            raise ValueError("kaputt")
        return original(msg)

    monkeypatch.setattr(mail_intake, "_client", lambda: fake)
    monkeypatch.setattr(mail_intake, "_kandidaten_aus_nachricht", _kaputter_parser)

    ergebnis = mail_intake.pruefe_mail_eingang(tmp_db)

    assert ergebnis["gefunden"] == 2
    assert ergebnis["fehler"] == 1
    assert ergebnis["neu"] == 1


def test_leerer_text_ohne_kontaktdaten_erzeugt_keinen_vorschlag(tmp_db, monkeypatch):
    _konfigurieren(monkeypatch)
    fake = _FakeClient({b"1": _text_mail("<drei@example.com>", "Nur ein Gruss ohne Kontaktdaten.")})
    monkeypatch.setattr(mail_intake, "_client", lambda: fake)

    ergebnis = mail_intake.pruefe_mail_eingang(tmp_db)

    assert ergebnis["neu"] == 0
    assert queries.list_vorschlaege(tmp_db, quelle="mail") == []
