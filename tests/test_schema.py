def test_schema_init_creates_tables(tmp_db):
    tables = {
        row["name"] for row in tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    for erwartet in ("kontakte", "telefonnummern", "emails", "adressen", "urls",
                      "projekte", "kontakte_projekte", "vorschlaege"):
        assert erwartet in tables


def test_foreign_keys_enforced(tmp_db):
    assert tmp_db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_kontakt_deletion_cascades(tmp_db):
    from db import queries

    kontakt_id = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [{"typ": "mobil", "nummer": "0791234567"}],
        "emails": [{"typ": "arbeit", "email": "anna@example.com"}],
        "adressen": [{"typ": "arbeit", "strasse": "Teststrasse 1", "plz": "8000", "ort": "Zuerich"}],
        "urls": [{"typ": "homepage", "url": "https://example.com"}],
    })
    queries.delete_kontakt(tmp_db, kontakt_id)

    assert tmp_db.execute("SELECT COUNT(*) FROM telefonnummern WHERE kontakt_id = ?", (kontakt_id,)).fetchone()[0] == 0
    assert tmp_db.execute("SELECT COUNT(*) FROM emails WHERE kontakt_id = ?", (kontakt_id,)).fetchone()[0] == 0
    assert tmp_db.execute("SELECT COUNT(*) FROM adressen WHERE kontakt_id = ?", (kontakt_id,)).fetchone()[0] == 0
    assert tmp_db.execute("SELECT COUNT(*) FROM urls WHERE kontakt_id = ?", (kontakt_id,)).fetchone()[0] == 0
