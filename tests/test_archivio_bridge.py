import sqlite3

import pytest

from archivio_bridge.anbindung import hole_kandidaten
from db import queries


@pytest.fixture
def archivio_db(tmp_path):
    """Baut eine winzige, synthetische Archivio-DB nach (documents/document_content/mails)."""
    pfad = tmp_path / "archivio-test.db"
    conn = sqlite3.connect(pfad)
    conn.executescript("""
        CREATE TABLE documents (id INTEGER PRIMARY KEY, source_type TEXT);
        CREATE TABLE document_content (document_id INTEGER, content TEXT);
        CREATE TABLE mails (document_id INTEGER, sender TEXT, date TEXT);
    """)

    def _mail(doc_id, sender, content, datum):
        conn.execute("INSERT INTO documents (id, source_type) VALUES (?, 'email')", (doc_id,))
        conn.execute("INSERT INTO document_content (document_id, content) VALUES (?, ?)", (doc_id, content))
        conn.execute("INSERT INTO mails (document_id, sender, date) VALUES (?, ?, ?)", (doc_id, sender, datum))

    sig_vollstaendig = (
        "Hallo\n\nAnna Beispiel\nProjektleiterin\nBeispiel AG\n"
        "Musterstrasse 1\n8000 Zuerich\nT 044 123 45 67\nanna@beispiel.ch"
    )
    # Absender mit 2 Mails, vollstaendiger Signatur (Telefon + Firma) -> Kandidat
    _mail(1, "anna@beispiel.ch", sig_vollstaendig, "2026-01-01")
    _mail(2, "anna@beispiel.ch", sig_vollstaendig, "2026-01-05")

    # Absender mit nur 1 Mail -> zu wenig Korrespondenz, kein Kandidat
    _mail(3, "einmalig@irgendwo.ch", sig_vollstaendig.replace("anna@beispiel.ch", "einmalig@irgendwo.ch"), "2026-01-01")

    # Absender mit 2 Mails, aber KEINE Firma in der Signatur -> kein Kandidat
    sig_ohne_firma = "Bob Niemand\n044 999 88 77\nbob@nirgends.ch"
    _mail(4, "bob@nirgends.ch", sig_ohne_firma, "2026-01-01")
    _mail(5, "bob@nirgends.ch", sig_ohne_firma, "2026-01-02")

    # Absender mit 2 Mails, Firma + Telefon, aber bereits als Kontakt in Rubrica
    sig_bekannt = (
        "Carla Kunde\nKunde AG\nMusterweg 2\n9000 St. Gallen\nT 071 555 44 33\ncarla@bestehend.ch"
    )
    _mail(6, "carla@bestehend.ch", sig_bekannt, "2026-01-01")
    _mail(7, "carla@bestehend.ch", sig_bekannt, "2026-01-02")

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


def test_bereits_bestehender_kontakt_wird_uebersprungen(archivio_db, tmp_db):
    queries.create_kontakt(tmp_db, {
        "vorname": "Carla", "nachname": "Kunde",
        "emails": [{"typ": "arbeit", "email": "carla@bestehend.ch"}],
    })
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    mails = {k["emails"][0]["email"] for k in kandidaten if k["emails"]}
    assert "carla@bestehend.ch" not in mails


def test_kandidat_enthaelt_anzahl_mails(archivio_db, tmp_db):
    kandidaten = hole_kandidaten(archivio_db, tmp_db, min_mails=2)
    anna = next(k for k in kandidaten if k["emails"] and k["emails"][0]["email"] == "anna@beispiel.ch")
    assert anna["anzahl_mails"] == 2
