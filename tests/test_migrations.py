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


def test_kontakte_apple_uid_migration_fuegt_spalte_bei_bestehender_installation_hinzu():
    # Simuliert eine bestehende Installation von VOR dieser Aenderung (kontakte ohne
    # apple_uid-Spalte) - hier muss migrations.run() die Spalte per ALTER TABLE ergaenzen.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE kontakte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vorname TEXT NOT NULL DEFAULT '', nachname TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE telefonnummern (id INTEGER PRIMARY KEY, kontakt_id INTEGER, typ TEXT NOT NULL DEFAULT '', nummer TEXT NOT NULL);
        CREATE TABLE emails (id INTEGER PRIMARY KEY, kontakt_id INTEGER, typ TEXT NOT NULL DEFAULT '', email TEXT NOT NULL);
        CREATE TABLE vorschlaege (
            id INTEGER PRIMARY KEY, kontakt_id INTEGER, quelle TEXT NOT NULL DEFAULT 'import',
            status TEXT NOT NULL DEFAULT 'offen', rohdaten TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );
        CREATE TABLE projekte (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
        CREATE TABLE _migrations (id TEXT PRIMARY KEY, applied_at TEXT);
    """)
    conn.execute("INSERT INTO kontakte (id, vorname, nachname) VALUES (1, 'Anna', 'Muster')")

    migrations.run(conn)

    spalten = {row["name"] for row in conn.execute("PRAGMA table_info(kontakte)")}
    assert "apple_uid" in spalten
    assert conn.execute("SELECT apple_uid FROM kontakte WHERE id = 1").fetchone()["apple_uid"] is None


def test_init_schema_reihenfolge_gegen_bestehende_installation_ohne_apple_uid():
    # Regression (Produktivfehler auf dem iMac nach dem Update auf 1.2.0): init_schema()
    # (db/connection.py) fuehrt IMMER zuerst schema.sql aus (CREATE TABLE IF NOT EXISTS -
    # ein no-op bei einer bereits bestehenden kontakte-Tabelle OHNE apple_uid) und ERST
    # DANACH migrations.run() (das die Spalte ergaenzt). Ein "CREATE INDEX ... ON
    # kontakte(apple_uid)" direkt in schema.sql (statt in der Migration) liess genau diese
    # schema.sql-Ausfuehrung mit "no such column: apple_uid" abstuerzen, noch bevor die
    # Migration ueberhaupt zum Zug kam - der Server startete dadurch gar nicht mehr.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Alte kontakte-Tabelle OHNE apple_uid, wie auf einer Installation von vor 1.2.0.
    conn.executescript("""
        CREATE TABLE kontakte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vorname TEXT NOT NULL DEFAULT '', nachname TEXT NOT NULL DEFAULT '',
            firma TEXT NOT NULL DEFAULT '', rolle TEXT NOT NULL DEFAULT '',
            kategorie TEXT NOT NULL DEFAULT '', notizen TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'aktiv',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );
        CREATE TABLE _migrations (id TEXT PRIMARY KEY, applied_at TEXT);
    """)
    conn.execute("INSERT INTO kontakte (id, vorname, nachname) VALUES (1, 'Anna', 'Muster')")

    schema = Path(__file__).parent.parent / "db" / "schema.sql"
    with conn:
        conn.executescript(schema.read_text(encoding="utf-8"))  # darf NICHT werfen
    migrations.run(conn)

    spalten = {row["name"] for row in conn.execute("PRAGMA table_info(kontakte)")}
    assert "apple_uid" in spalten
    assert conn.execute("SELECT vorname FROM kontakte WHERE id = 1").fetchone()["vorname"] == "Anna"


def test_kontakte_apple_uid_migration_auf_frischem_schema_ohne_fehler():
    # schema.sql enthaelt die Spalte apple_uid bereits (fuer frische Installationen) -
    # migrations.run() darf hier trotzdem nicht mit "duplicate column name" scheitern
    # (siehe db/migrations.py._kontakte_apple_uid).
    conn = _frisches_schema_ohne_migrationen()
    migrations.run(conn)
    migrations.run(conn)  # idempotent

    spalten = {row["name"] for row in conn.execute("PRAGMA table_info(kontakte)")}
    assert "apple_uid" in spalten
