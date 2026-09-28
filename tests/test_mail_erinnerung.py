import mail_erinnerung
from config import settings
from db import queries


class _FakeSMTP:
    def __init__(self):
        self.gesendet = []
        self.quit_aufgerufen = False

    def send_message(self, msg):
        self.gesendet.append(msg)

    def quit(self):
        self.quit_aufgerufen = True


def _konfiguriere_smtp(monkeypatch, **zusatz):
    smtp = {
        "host": "smtp.beispiel.ch", "port": 587,
        "username": "rubrica@beispiel.ch", "password": "geheim",
        "empfaenger": "fi@beispiel.ch",
    }
    smtp.update(zusatz)
    monkeypatch.setattr(settings, "_settings", {"smtp": smtp})


def _offener_vorschlag_vor(tmp_db, stunden: float, vorname="Anna", nachname="Muster", quelle="mail") -> int:
    vid = queries.create_vorschlag(tmp_db, {"vorname": vorname, "nachname": nachname}, quelle=quelle)
    # Einfacher und robuster als Datumsrechnung: created_at direkt weit in die
    # Vergangenheit setzen, wenn "laengst faellig" gemeint ist, sonst auf "gerade eben".
    if stunden >= 24:
        tmp_db.execute("UPDATE vorschlaege SET created_at = '2000-01-01T00:00:00Z' WHERE id = ?", (vid,))
    else:
        tmp_db.execute("UPDATE vorschlaege SET created_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?", (vid,))
    tmp_db.commit()
    return vid


def _offener_vorschlag_seit(tmp_db, iso_created_at: str, vorname="Anna", nachname="Muster", quelle="mail") -> int:
    vid = queries.create_vorschlag(tmp_db, {"vorname": vorname, "nachname": nachname}, quelle=quelle)
    tmp_db.execute("UPDATE vorschlaege SET created_at = ? WHERE id = ?", (iso_created_at, vid))
    tmp_db.commit()
    return vid


def test_konfiguriert_erfordert_host_und_empfaenger(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {})
    assert mail_erinnerung.konfiguriert() is False
    _konfiguriere_smtp(monkeypatch)
    assert mail_erinnerung.konfiguriert() is True


def test_vorschlaege_faellig_fuer_erinnerung_findet_nur_alte_offene(tmp_db):
    faelliger_id = _offener_vorschlag_vor(tmp_db, 24)
    _offener_vorschlag_vor(tmp_db, 0, vorname="Bob", nachname="Neu")

    faellige = queries.vorschlaege_faellig_fuer_erinnerung(tmp_db, 24)
    assert [v["id"] for v in faellige] == [faelliger_id]


def test_vorschlaege_faellig_ignoriert_bereits_erinnerte(tmp_db):
    vid = _offener_vorschlag_vor(tmp_db, 24)
    queries.markiere_erinnerung_gesendet(tmp_db, [vid])

    assert queries.vorschlaege_faellig_fuer_erinnerung(tmp_db, 24) == []


def test_vorschlaege_faellig_ignoriert_bereits_bestaetigte(tmp_db):
    vid = _offener_vorschlag_vor(tmp_db, 24)
    queries.set_vorschlag_status(tmp_db, vid, "bestaetigt")

    assert queries.vorschlaege_faellig_fuer_erinnerung(tmp_db, 24) == []


def test_markiere_erinnerung_gesendet_setzt_zeitstempel(tmp_db):
    vid = _offener_vorschlag_vor(tmp_db, 24)
    queries.markiere_erinnerung_gesendet(tmp_db, [vid])

    vorschlag = queries.get_vorschlag(tmp_db, vid)
    assert vorschlag["erinnerung_gesendet_am"]


def test_sende_erinnerung_ohne_konfiguration_tut_nichts(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {})
    _offener_vorschlag_vor(tmp_db, 24)

    ergebnis = mail_erinnerung.sende_erinnerung(tmp_db)
    assert ergebnis == {"aktiv": False, "anzahl": 0}


def test_sende_erinnerung_ohne_faellige_vorschlaege_verschickt_nichts(tmp_db, monkeypatch):
    _konfiguriere_smtp(monkeypatch)
    fake = _FakeSMTP()
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: fake)
    _offener_vorschlag_vor(tmp_db, 0)  # gerade erst offen, noch nicht faellig

    ergebnis = mail_erinnerung.sende_erinnerung(tmp_db)
    assert ergebnis == {"aktiv": True, "anzahl": 0}
    assert fake.gesendet == []


def test_sende_erinnerung_buendelt_mehrere_faellige_in_einer_mail(tmp_db, monkeypatch):
    """Nutzer-Vorgabe: kein Spam bei mehreren gleichzeitig faelligen Vorschlaegen -
    genau EIN send_message-Aufruf, egal wie viele faellig sind."""
    _konfiguriere_smtp(monkeypatch)
    fake = _FakeSMTP()
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: fake)
    v1 = _offener_vorschlag_vor(tmp_db, 24, vorname="Anna", nachname="Erste")
    v2 = _offener_vorschlag_vor(tmp_db, 24, vorname="Bob", nachname="Zweiter", quelle="kontakte_app")

    ergebnis = mail_erinnerung.sende_erinnerung(tmp_db)

    assert ergebnis == {"aktiv": True, "anzahl": 2}
    assert len(fake.gesendet) == 1
    assert fake.quit_aufgerufen is True
    text = fake.gesendet[0].get_payload(decode=True).decode("utf-8")
    assert "Anna Erste" in text
    assert "Bob Zweiter" in text
    assert "Mail" in text and "Kontakte.app" in text
    # beide wurden markiert - ein zweiter Lauf verschickt nichts mehr
    assert queries.get_vorschlag(tmp_db, v1)["erinnerung_gesendet_am"]
    assert queries.get_vorschlag(tmp_db, v2)["erinnerung_gesendet_am"]


def test_sende_erinnerung_meldet_jeden_vorschlag_nur_einmal(tmp_db, monkeypatch):
    """Nutzer-Vorgabe: keine taeglich wiederholte Mail - ein zweiter Lauf ohne neue
    faellige Vorschlaege verschickt nichts, obwohl der erste weiterhin offen ist."""
    _konfiguriere_smtp(monkeypatch)
    fake = _FakeSMTP()
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: fake)
    _offener_vorschlag_vor(tmp_db, 24)

    mail_erinnerung.sende_erinnerung(tmp_db)
    ergebnis_zweiter_lauf = mail_erinnerung.sende_erinnerung(tmp_db)

    assert ergebnis_zweiter_lauf == {"aktiv": True, "anzahl": 0}
    assert len(fake.gesendet) == 1


def test_pruefe_und_beschreibe_ohne_konfiguration(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "_settings", {})
    assert "nicht konfiguriert" in mail_erinnerung.pruefe_und_beschreibe(tmp_db)


def test_pruefe_und_beschreibe_fasst_versand_zusammen(tmp_db, monkeypatch):
    _konfiguriere_smtp(monkeypatch)
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: _FakeSMTP())
    _offener_vorschlag_vor(tmp_db, 24)

    text = mail_erinnerung.pruefe_und_beschreibe(tmp_db)
    assert "1" in text and "verschickt" in text


def test_pruefe_und_beschreibe_faengt_versandfehler_ab(tmp_db, monkeypatch):
    _konfiguriere_smtp(monkeypatch)

    def _wirft():
        raise ConnectionRefusedError("nope")

    monkeypatch.setattr(mail_erinnerung, "_verbindung", _wirft)
    _offener_vorschlag_vor(tmp_db, 24)

    text = mail_erinnerung.pruefe_und_beschreibe(tmp_db)
    assert "fehlgeschlagen" in text


def test_sende_testmail_ohne_konfiguration(monkeypatch):
    monkeypatch.setattr(settings, "_settings", {})
    assert "Kein SMTP" in mail_erinnerung.sende_testmail()


def test_sende_testmail_verschickt_unabhaengig_von_faelligen_vorschlaegen(monkeypatch):
    _konfiguriere_smtp(monkeypatch)
    fake = _FakeSMTP()
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: fake)

    text = mail_erinnerung.sende_testmail()
    assert "verschickt" in text
    assert len(fake.gesendet) == 1


def test_verbindung_nutzt_starttls_ausser_bei_port_465(monkeypatch):
    """Port 465 = implizites TLS (SMTP_SSL), alles andere (typisch 587) = STARTTLS -
    ein falscher Modus fuehrt sonst zu einem stillen Verbindungsfehler."""
    aufrufe = []

    class _Aufgezeichnet:
        def __init__(self, host, port, timeout=None):
            aufrufe.append(("plain", host, port))

        def starttls(self):
            aufrufe.append("starttls")

        def login(self, u, p):
            aufrufe.append(("login", u, p))

    class _AufgezeichnetSSL:
        def __init__(self, host, port, timeout=None):
            aufrufe.append(("ssl", host, port))

        def login(self, u, p):
            aufrufe.append(("login", u, p))

    monkeypatch.setattr(mail_erinnerung.smtplib, "SMTP", _Aufgezeichnet)
    monkeypatch.setattr(mail_erinnerung.smtplib, "SMTP_SSL", _AufgezeichnetSSL)

    monkeypatch.setattr(settings, "_settings", {"smtp": {
        "host": "smtp.beispiel.ch", "port": 587, "username": "u", "password": "p", "empfaenger": "e@x.ch",
    }})
    mail_erinnerung._verbindung()
    assert aufrufe == [("plain", "smtp.beispiel.ch", 587), "starttls", ("login", "u", "p")]

    aufrufe.clear()
    monkeypatch.setattr(settings, "_settings", {"smtp": {
        "host": "smtp.beispiel.ch", "port": 465, "username": "u", "password": "p", "empfaenger": "e@x.ch",
    }})
    mail_erinnerung._verbindung()
    assert aufrufe == [("ssl", "smtp.beispiel.ch", 465), ("login", "u", "p")]


# ── Datumsformat in der Mail (Nutzer-Meldung: "seit 2026-09-25T14:04:35Z offen" war
# schwer lesbar) ──────────────────────────────────────────────────────────────────

def test_lesbares_datum_formatiert_iso_als_zeit_und_datum():
    assert mail_erinnerung._lesbares_datum("2026-09-25T14:04:35Z") == "14:04 25.09.2026"


def test_lesbares_datum_faellt_bei_unerwartetem_format_auf_rohwert_zurueck():
    assert mail_erinnerung._lesbares_datum("nicht-iso") == "nicht-iso"


def test_erinnerung_mail_enthaelt_lesbares_datum_nicht_die_iso_rohform(tmp_db, monkeypatch):
    _konfiguriere_smtp(monkeypatch)
    fake = _FakeSMTP()
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: fake)
    _offener_vorschlag_seit(tmp_db, "2026-09-25T14:04:35Z")

    mail_erinnerung.sende_erinnerung(tmp_db)

    text = fake.gesendet[0].get_payload(decode=True).decode("utf-8")
    assert "14:04 25.09.2026" in text
    assert "2026-09-25T14:04:35Z" not in text


# ── Zweite Erinnerung an eine Ausweich-Adresse (Nutzer-Anlass: "wenn Empfänger 1 in
# den Ferien ist") ────────────────────────────────────────────────────────────────

def _konfiguriere_eskalation(monkeypatch, tage=3):
    _konfiguriere_smtp(monkeypatch, empfaenger2="stellvertretung@beispiel.ch", eskalation_tage=tage)


def _offener_vorschlag_vor_tagen(tmp_db, tage: float, **kwargs) -> int:
    from datetime import datetime, timedelta, timezone
    iso = (datetime.now(timezone.utc) - timedelta(days=tage)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _offener_vorschlag_seit(tmp_db, iso, **kwargs)


def test_eskalation_konfiguriert_erfordert_zweite_adresse_und_tage(tmp_db, monkeypatch):
    _konfiguriere_smtp(monkeypatch)  # keine zweite Adresse/Tage
    assert mail_erinnerung.eskalation_konfiguriert() is False

    _konfiguriere_eskalation(monkeypatch, tage=3)
    assert mail_erinnerung.eskalation_konfiguriert() is True

    _konfiguriere_smtp(monkeypatch, empfaenger2="stellvertretung@beispiel.ch", eskalation_tage=0)
    assert mail_erinnerung.eskalation_konfiguriert() is False


def test_vorschlaege_faellig_fuer_eskalation_findet_nur_genug_alte(tmp_db):
    alter_id = _offener_vorschlag_vor_tagen(tmp_db, 4)
    _offener_vorschlag_vor_tagen(tmp_db, 1, vorname="Bob", nachname="Neu")

    faellige = queries.vorschlaege_faellig_fuer_eskalation(tmp_db, 3 * 24)
    assert [v["id"] for v in faellige] == [alter_id]


def test_eskalation_und_erinnerung_blockieren_sich_nicht_gegenseitig(tmp_db):
    """Ein Vorschlag kann die erste Erinnerung schon bekommen haben (erinnerung_gesendet_am
    gesetzt) und trotzdem noch fuer die zweite faellig sein - eigenes Feld, siehe Schema."""
    vid = _offener_vorschlag_vor_tagen(tmp_db, 4)
    queries.markiere_erinnerung_gesendet(tmp_db, [vid])

    assert [v["id"] for v in queries.vorschlaege_faellig_fuer_eskalation(tmp_db, 3 * 24)] == [vid]


def test_sende_eskalation_ohne_konfiguration_tut_nichts(tmp_db, monkeypatch):
    _konfiguriere_smtp(monkeypatch)  # nur die erste Adresse, keine Eskalation
    _offener_vorschlag_vor_tagen(tmp_db, 10)

    assert mail_erinnerung.sende_eskalation(tmp_db) == {"aktiv": False, "anzahl": 0}


def test_sende_eskalation_verschickt_an_zweite_adresse(tmp_db, monkeypatch):
    _konfiguriere_eskalation(monkeypatch, tage=3)
    fake = _FakeSMTP()
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: fake)
    vid = _offener_vorschlag_vor_tagen(tmp_db, 4, vorname="Anna", nachname="Lang-Offen")

    ergebnis = mail_erinnerung.sende_eskalation(tmp_db)

    assert ergebnis == {"aktiv": True, "anzahl": 1}
    assert len(fake.gesendet) == 1
    assert fake.gesendet[0]["To"] == "stellvertretung@beispiel.ch"
    text = fake.gesendet[0].get_payload(decode=True).decode("utf-8")
    assert "Anna Lang-Offen" in text
    assert "3 Tagen" in text
    assert queries.get_vorschlag(tmp_db, vid)["eskalation_gesendet_am"]


def test_sende_eskalation_meldet_jeden_vorschlag_nur_einmal(tmp_db, monkeypatch):
    _konfiguriere_eskalation(monkeypatch, tage=3)
    fake = _FakeSMTP()
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: fake)
    _offener_vorschlag_vor_tagen(tmp_db, 4)

    mail_erinnerung.sende_eskalation(tmp_db)
    zweiter_lauf = mail_erinnerung.sende_eskalation(tmp_db)

    assert zweiter_lauf == {"aktiv": True, "anzahl": 0}
    assert len(fake.gesendet) == 1


def test_pruefe_und_beschreibe_erwaehnt_eskalation_wenn_konfiguriert(tmp_db, monkeypatch):
    _konfiguriere_eskalation(monkeypatch, tage=3)
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: _FakeSMTP())
    _offener_vorschlag_vor_tagen(tmp_db, 4)

    text = mail_erinnerung.pruefe_und_beschreibe(tmp_db)
    assert "Erinnerungsmail mit 1 Vorschlägen verschickt." in text
    assert "Zweite Erinnerung mit 1 Vorschlägen an die zweite Adresse verschickt." in text


def test_pruefe_und_beschreibe_ohne_eskalation_erwaehnt_sie_nicht(tmp_db, monkeypatch):
    _konfiguriere_smtp(monkeypatch)  # keine Eskalation konfiguriert
    monkeypatch.setattr(mail_erinnerung, "_verbindung", lambda: _FakeSMTP())
    _offener_vorschlag_vor(tmp_db, 24)

    text = mail_erinnerung.pruefe_und_beschreibe(tmp_db)
    assert "Zweite Erinnerung" not in text
