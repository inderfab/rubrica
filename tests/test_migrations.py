import sqlite3
from pathlib import Path

from db import migrations


def _frisches_schema_ohne_migrationen() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema = Path(__file__).parent.parent / "db" / "schema.sql"
    conn.executescript(schema.read_text(encoding="utf-8"))
    return conn


def test_migration_mappt_telefon_und_email_typen_auf_direkt_privat_allgemein():
    conn = _frisches_schema_ohne_migrationen()
    with conn:
        conn.execute("INSERT INTO kontakte (id, vorname, nachname) VALUES (1, 'Anna', 'Muster')")
        for typ, nummer in [
            ("work", "052 111 11 11"), ("cell", "079 222 22 22"), ("home", "052 333 33 33"),
            ("main", "052 444 44 44"), ("arbeit", "052 555 55 55"), ("mobil", "079 666 66 66"),
        ]:
            conn.execute("INSERT INTO telefonnummern (kontakt_id, typ, nummer) VALUES (1, ?, ?)", (typ, nummer))
        for typ, email in [("internet", "a@b.ch"), ("home", "privat@b.ch"), ("main", "info@b.ch")]:
            conn.execute("INSERT INTO emails (kontakt_id, typ, email) VALUES (1, ?, ?)", (typ, email))

    migrations.run(conn)

    telefon_typen = {row["nummer"]: row["typ"] for row in conn.execute("SELECT nummer, typ FROM telefonnummern")}
    assert telefon_typen["052 111 11 11"] == "Direkt"   # work
    assert telefon_typen["079 222 22 22"] == "Privat"   # cell
    assert telefon_typen["052 333 33 33"] == "Privat"   # home
    assert telefon_typen["052 444 44 44"] == "Allgemein"  # main
    assert telefon_typen["052 555 55 55"] == "Direkt"   # arbeit
    assert telefon_typen["079 666 66 66"] == "Privat"   # mobil

    email_typen = {row["email"]: row["typ"] for row in conn.execute("SELECT email, typ FROM emails")}
    assert email_typen["a@b.ch"] == "Direkt"       # internet (Apple-generisch)
    assert email_typen["privat@b.ch"] == "Privat"  # home
    assert email_typen["info@b.ch"] == "Allgemein"  # main


def test_migration_ist_idempotent():
    conn = _frisches_schema_ohne_migrationen()
    with conn:
        conn.execute("INSERT INTO kontakte (id, vorname, nachname) VALUES (1, 'Anna', 'Muster')")
        conn.execute("INSERT INTO telefonnummern (kontakt_id, typ, nummer) VALUES (1, 'work', '052 111 11 11')")

    migrations.run(conn)
    migrations.run(conn)  # zweiter Aufruf darf nichts mehr aendern (bereits in _migrations vermerkt)

    typ = conn.execute("SELECT typ FROM telefonnummern").fetchone()["typ"]
    assert typ == "Direkt"
