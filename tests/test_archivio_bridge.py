import sqlite3

import pytest

from archivio_bridge.anbindung import hole_kandidaten, liste_postfaecher, markiere_status
from db import queries


def _neue_signatur_db(pfad):
    conn = sqlite3.connect(pfad)
    conn.executescript("""
        CREATE TABLE signatur_quelle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            absender TEXT, absender_email TEXT, empfaenger TEXT, cc TEXT,
            postfach TEXT, projekt TEXT, betreff TEXT, text TEXT, datum TEXT,
            status TEXT NOT NULL DEFAULT 'pending', status_updated_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
    """)
    return conn


def _mail(conn, message_id, absender_email, text, datum, postfach="", projekt="", status="pending"):
    conn.execute(
        "INSERT INTO signatur_quelle (message_id, absender_email, postfach, projekt, text, datum, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (message_id, absender_email, postfach, projekt, text, datum, status),
    )


@pytest.fixture
def archivio_db(tmp_path):
    """Baut eine winzige, synthetische Archivio-Signatur-DB nach (signatur_quelle)."""
    pfad = tmp_path / "archivio-test.db"
    conn = _neue_signatur_db(pfad)

    sig_vollstaendig = (
        "Hallo\n\nAnna Beispiel\nProjektleiterin\nBeispiel AG\n"
        "Musterstrasse 1\n8000 Zuerich\nT 044 123 45 67\nanna@beispiel.ch"
    )
    # Absender mit 2 Mails, vollstaendiger Signatur (Telefon + Firma) -> Kandidat
    _mail(conn, "m1", "anna@beispiel.ch", sig_vollstaendig, "2026-01-01", postfach="200_projekt", projekt="200 Projekt")
    _mail(conn, "m2", "anna@beispiel.ch", sig_vollstaendig, "2026-01-05", postfach="200_projekt", projekt="200 Projekt")

    # Absender mit nur 1 Mail -> zu wenig Korrespondenz, kein Kandidat
    _mail(conn, "m3", "einmalig@irgendwo.ch",
          sig_vollstaendig.replace("anna@beispiel.ch", "einmalig@irgendwo.ch"), "2026-01-01")

    # Absender mit 2 Mails, aber KEINE Firma in der Signatur -> kein Kandidat
    sig_ohne_firma = "Bob Niemand\n044 999 88 77\nbob@nirgends.ch"
    _mail(conn, "m4", "bob@nirgends.ch", sig_ohne_firma, "2026-01-01")
    _mail(conn, "m5", "bob@nirgends.ch", sig_ohne_firma, "2026-01-02")

    # Absender mit 2 Mails, Firma + Telefon, aber bereits als Kontakt in Rubrica
    sig_bekannt = "Carla Kunde\nKunde AG\nMusterweg 2\n9000 St. Gallen\nT 071 555 44 33\ncarla@bestehend.ch"
    _mail(conn, "m6", "carla@bestehend.ch", sig_bekannt, "2026-01-01")
    _mail(conn, "m7", "carla@bestehend.ch", sig_bekannt, "2026-01-02")

    # Eigene Mitarbeiterin - nie ein Kandidat, egal wie vollstaendig die Signatur ist.
    _mail(conn, "m8", "fi@strut.ch", sig_vollstaendig.replace("anna@beispiel.ch", "fi@strut.ch"), "2026-01-01")
    _mail(conn, "m9", "fi@strut.ch", sig_vollstaendig.replace("anna@beispiel.ch", "fi@strut.ch"), "2026-01-02")

    conn.commit()
    conn.close()
    return str(pfad)


def test_kandidat_mit_telefon_und_firma_wird_gefunden(archivio_db, tmp_db):
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "anna@beispiel.ch" in mails


def test_zu_wenig_korrespondenz_wird_ausgeschlossen(archivio_db, tmp_db):
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "einmalig@irgendwo.ch" not in mails


def test_signatur_ohne_firma_wird_ausgeschlossen(archivio_db, tmp_db):
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "bob@nirgends.ch" not in mails


def test_eigene_mitarbeiter_werden_nie_kandidat(archivio_db, tmp_db):
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "fi@strut.ch" not in mails


def test_automatisierte_systemadressen_werden_nie_kandidat(tmp_path, tmp_db):
    """Realer Fund: eine no-reply-Benachrichtigung (z.B. Plot-/Druckauftrag) kann
    zufaellig einen vollstaendig aussehenden Namen/Telefon/E-Mail im Text enthalten
    (z.B. die Daten des internen Bestellers in der Vorlage) - trotzdem nie ein
    echter Korrespondenzpartner."""
    pfad = tmp_path / "archivio-noreply.db"
    conn = _neue_signatur_db(pfad)
    sig = "Hans Muster\nMuster AG\nMusterweg 1\n8000 Zuerich\nT 044 111 22 33\nhans@muster.ch"
    _mail(conn, "m1", "no-reply@plotjet.com", sig, "2026-01-01")
    _mail(conn, "m2", "no-reply@plotjet.com", sig, "2026-01-02")
    conn.commit()
    conn.close()

    kandidaten = hole_kandidaten(str(pfad), tmp_db, min_mails=2)
    assert kandidaten == []


def test_bereits_bestehender_kontakt_wird_uebersprungen_und_in_db_abgelehnt(archivio_db, tmp_db):
    queries.create_kontakt(tmp_db, {
        "vorname": "Carla", "nachname": "Kunde",
        "emails": [{"typ": "arbeit", "email": "carla@bestehend.ch"}],
    })
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "carla@bestehend.ch" not in mails

    # Die zugrundeliegenden Mails wurden automatisch als 'abgelehnt' markiert,
    # damit sie bei kuenftigen Scans nicht wieder geprueft werden.
    conn = sqlite3.connect(archivio_db)
    status = {r[0] for r in conn.execute(
        "SELECT status FROM signatur_quelle WHERE absender_email = 'carla@bestehend.ch'"
    )}
    conn.close()
    assert status == {"abgelehnt"}


def test_kandidat_enthaelt_anzahl_mails(archivio_db, tmp_db):
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    anna = next(k for k in kandidaten if k["emails"] and k["emails"][0]["email"] == "anna@beispiel.ch")
    assert anna["anzahl_mails"] == 2


def test_dublette_per_name_auch_bei_anderer_mailadresse_erkannt(archivio_db, tmp_db):
    queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Beispiel",
        "emails": [{"typ": "arbeit", "email": "andere-adresse@example.com"}],
    })
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "anna@beispiel.ch" not in mails


def test_dublette_per_telefon_erkannt(archivio_db, tmp_db):
    kontakt_id = queries.create_kontakt(tmp_db, {"vorname": "Jemand", "nachname": "Anders"})
    queries.update_kontakt(tmp_db, kontakt_id, {
        "vorname": "Jemand", "nachname": "Anders",
        "telefonnummern": [{"typ": "arbeit", "nummer": "044 123 45 67"}],
    })
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "anna@beispiel.ch" not in mails


def test_kandidat_ohne_email_wird_ausgeschlossen(tmp_path, tmp_db):
    pfad = tmp_path / "archivio-ohne-email.db"
    conn = _neue_signatur_db(pfad)
    sig = "Peter Muster\nMuster AG\n044 123 45 67"
    _mail(conn, "m1", "", sig, "2026-01-01")
    _mail(conn, "m2", "", sig, "2026-01-02")
    conn.commit()
    conn.close()

    kandidaten = hole_kandidaten(str(pfad), tmp_db, min_mails=2)
    assert kandidaten == []


def test_mehrere_versuche_pro_absender_bei_unvollstaendiger_erster_mail(tmp_path, tmp_db):
    """Simuliert eine unvollstaendige neueste Mail (z.B. E-Mail fehlt in der
    Signatur) - eine aeltere Mail desselben Absenders liefert ein vollstaendiges
    Ergebnis; hole_kandidaten soll dann die aeltere Mail verwenden."""
    pfad = tmp_path / "archivio-mehrere-versuche.db"
    conn = _neue_signatur_db(pfad)
    sig_gekappt = "Peter Muster\nMuster AG\n044 123 45 67"  # keine E-Mail
    sig_vollstaendig = "Peter Muster\nMuster AG\n044 123 45 67\npeter@muster.ch"
    _mail(conn, "m1", "peter@muster.ch", sig_gekappt, "2026-01-05")
    _mail(conn, "m2", "peter@muster.ch", sig_vollstaendig, "2026-01-01")
    conn.commit()
    conn.close()

    kandidaten = hole_kandidaten(str(pfad), tmp_db, min_mails=2)
    assert len(kandidaten) == 1
    assert kandidaten[0]["emails"][0]["email"] == "peter@muster.ch"


def test_zitierter_verlauf_wird_vor_signatursuche_abgeschnitten(tmp_path, tmp_db):
    """Realer Bug: Archivio liefert den vollen Thread-Text (aktuelle Nachricht +
    zitierter Verlauf mit fremden Signaturen). Ohne Abschneiden des Zitats wuerde
    die 'letzte Zeilen'-Heuristik die Signatur der AELTESTEN zitierten Person
    erwischen statt der des tatsaechlichen Absenders."""
    pfad = tmp_path / "archivio-thread.db"
    conn = _neue_signatur_db(pfad)
    text = (
        "Hallo zusammen\n\nHier meine Rueckmeldung.\n\n"
        "Freundliche Gruesse\n\nFabio Indergand\nStrut Architekten AG\n"
        "Neuwiesenstrasse 69, 8400 Winterthur\nT 052 214 20 37\nfi@strut.ch\n\n"
        "Von: Marcel Mueller <marcel@andere-firma.ch>\n"
        "Gesendet: Montag, 1. Januar 2026\nAn: Fabio Indergand\nBetreff: AW: Test\n\n"
        "Alte Nachricht mit ganz anderer Signatur.\n\n"
        "Gruss\nMarcel Mueller\nAndere Firma AG\nMusterweg 3\n9000 St. Gallen\nT 071 111 22 33\nmarcel@andere-firma.ch"
    )
    _mail(conn, "m1", "fi@strut.ch", text, "2026-01-05")
    _mail(conn, "m2", "fi@strut.ch", text, "2026-01-06")
    conn.commit()
    conn.close()

    # fi@strut.ch ist eine eigene Mitarbeiterin und wird ausgefiltert - stattdessen
    # pruefen wir hier direkt die Kernfunktion, um die Zitat-Abschneidung isoliert
    # zu testen (unabhaengig vom Mitarbeiter-Filter).
    from archivio_bridge.anbindung import _ohne_zitat
    bereinigt = _ohne_zitat(text)
    assert "Fabio Indergand" in bereinigt
    assert "Marcel Mueller" not in bereinigt
    assert "Von:" not in bereinigt


def test_postfach_zuordnung_ergibt_gruppen_als_ordner(archivio_db, tmp_db):
    ordner_id = queries.get_or_create_projekt(tmp_db, "Projekt 200")
    queries.postfach_zuordnen(tmp_db, "200_projekt", ordner_id)

    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    anna = next(k for k in kandidaten if k["emails"] and k["emails"][0]["email"] == "anna@beispiel.ch")
    assert anna["gruppen_als_ordner"] == ["Projekt 200"]


def test_kandidat_ohne_postfach_zuordnung_hat_leere_gruppen_liste(archivio_db, tmp_db):
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    anna = next(k for k in kandidaten if k["emails"] and k["emails"][0]["email"] == "anna@beispiel.ch")
    assert anna["gruppen_als_ordner"] == []


def test_postfaecher_filter_beschraenkt_kandidaten(archivio_db, tmp_db):
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2, postfaecher=["ein-anderes-postfach"])
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "anna@beispiel.ch" not in mails  # ihr Postfach war nicht in der Auswahl


def test_bereits_entschiedene_mails_werden_nicht_erneut_gescannt(archivio_db, tmp_db):
    markiere_status(archivio_db, "anna@beispiel.ch", "uebernommen")
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "anna@beispiel.ch" not in mails


def test_liste_postfaecher_gibt_distinkte_paare(archivio_db):
    postfaecher = liste_postfaecher(archivio_db)
    eintraege = {(p["postfach"], p["projekt"]) for p in postfaecher}
    assert ("200_projekt", "200 Projekt") in eintraege


def test_titelname_wird_durch_email_und_textverifikation_korrigiert(tmp_path, tmp_db):
    """Realer Fund: parse_signatur erkannte 'Projektleitung Systeme' als Name, weil
    die Zeile oberflaechlich wie zwei grossgeschriebene Woerter aussieht. Aus der
    Mailadresse h.minder@gilgen.com abgeleitet + im Volltext verifiziert soll der
    echte Name (aus einer Gruss-/Signaturzeile) gefunden werden."""
    pfad = tmp_path / "archivio-titelname.db"
    conn = _neue_signatur_db(pfad)
    text = (
        "Hallo zusammen\n\nAnbei die gewuenschten Unterlagen.\n\n"
        "Freundliche Gruesse\n\nHanspeter Minder\nProjektleitung Systeme\nGilgen Logistics AG\n"
        "Wangentalstrasse 252, 3173 Oberwangen\nT +41 31 985 35 21\nH.Minder@gilgen.com"
    )
    _mail(conn, "m1", "H.Minder@gilgen.com", text, "2026-01-01")
    _mail(conn, "m2", "H.Minder@gilgen.com", text, "2026-01-02")
    conn.commit()
    conn.close()

    kandidaten = hole_kandidaten(str(pfad), tmp_db, min_mails=2)
    assert len(kandidaten) == 1
    assert kandidaten[0]["vorname"] == "Hanspeter"
    assert kandidaten[0]["nachname"] == "Minder"


def test_ist_plausibler_personenname():
    from archivio_bridge.anbindung import _ist_plausibler_personenname
    assert _ist_plausibler_personenname("Anna", "Muster") is True
    assert _ist_plausibler_personenname("Roland", "GUNZENHAUSER") is True
    assert _ist_plausibler_personenname("Projektleitung", "Systeme") is False
    assert _ist_plausibler_personenname("EINWOHNERGEMEINDE", "DERENDINGEN") is False
    assert _ist_plausibler_personenname("", "") is False


def test_name_aus_email():
    from archivio_bridge.anbindung import _name_aus_email
    assert _name_aus_email("h.minder@gilgen.com") == ("H", "Minder")
    assert _name_aus_email("anna.muster@example.ch") == ("Anna", "Muster")
    assert _name_aus_email("info@example.ch") == ("", "")
    assert _name_aus_email("nur-ein-teil-ohne-punkt@example.ch") == ("", "")


def test_name_bleibt_unveraendert_wenn_keine_ableitung_aus_email_moeglich(tmp_path, tmp_db):
    """Wenn sich aus der Mailadresse kein Name ableiten laesst (z.B. generisches
    info@), bleibt der urspruengliche (ggf. unplausible) Name stehen statt auf leer
    zurueckgesetzt zu werden - der Kandidat erscheint weiterhin (Firma/Telefon/
    E-Mail sind ja korrekt), der Nutzer kann den Namen ueber "Bearbeiten" von Hand
    korrigieren."""
    pfad = tmp_path / "archivio-generisch.db"
    conn = _neue_signatur_db(pfad)
    text = "Project Manager\nAVS Systeme AG\nT 041 784 45 44\ninfo@avs-systeme.com"
    _mail(conn, "m1", "info@avs-systeme.com", text, "2026-01-01")
    _mail(conn, "m2", "info@avs-systeme.com", text, "2026-01-02")
    conn.commit()
    conn.close()

    kandidaten = hole_kandidaten(str(pfad), tmp_db, min_mails=2)
    assert len(kandidaten) == 1
    assert kandidaten[0]["vorname"] == "Project"
    assert kandidaten[0]["nachname"] == "Manager"


def test_postfach_zuordnen_und_wieder_aufheben(tmp_db):
    ordner_id = queries.get_or_create_projekt(tmp_db, "Testordner")
    queries.postfach_zuordnen(tmp_db, "irgendein_postfach", ordner_id)

    zuordnungen = queries.postfach_zuordnungen(tmp_db)
    assert zuordnungen["irgendein_postfach"] == {"projekt_id": ordner_id, "name": "Testordner"}

    queries.postfach_zuordnen(tmp_db, "irgendein_postfach", None)
    assert "irgendein_postfach" not in queries.postfach_zuordnungen(tmp_db)
