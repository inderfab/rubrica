from __future__ import annotations

import sqlite3

# Reihenfolge = Anwendungsreihenfolge. Neue Migrationen unten anhaengen, bestehende nie aendern.
# Solange Rubrica noch nicht produktiv im Einsatz ist, werden Schemaaenderungen direkt in
# schema.sql gepflegt statt per Migration - vermeidet doppelte Spalten-Definitionen.
_MIGRATIONS: list[tuple[str, str]] = [
    (
        "2026-07-13_telefon_email_typ_direkt_privat_allgemein",
        """
        -- Vereinheitlicht bisherige Telefon-/E-Mail-Kategorien (teils deutsch
        -- "arbeit"/"mobil"/"privat", teils englisch aus Apple-Importen
        -- "work"/"cell"/"home") auf die neuen drei Kategorien Direkt/Privat/
        -- Allgemein (siehe web/contacts.py TELEFON_EMAIL_TYPEN). Mobile Nummern
        -- gelten als privat; unbekannte/generische Typen (z.B. Apples
        -- "internet" fuer alle E-Mails) werden zu "Direkt" (sichtbar), damit
        -- nichts faelschlich verschwindet - siehe docs/konzept.md.
        UPDATE telefonnummern SET typ = 'Privat'
            WHERE lower(typ) IN ('home', 'privat', 'private', 'cell', 'mobil', 'iphone');
        UPDATE telefonnummern SET typ = 'Allgemein'
            WHERE lower(typ) IN ('main', 'allgemein');
        UPDATE telefonnummern SET typ = 'Direkt'
            WHERE typ NOT IN ('Privat', 'Allgemein');

        UPDATE emails SET typ = 'Privat'
            WHERE lower(typ) IN ('home', 'privat', 'private');
        UPDATE emails SET typ = 'Allgemein'
            WHERE lower(typ) IN ('main', 'allgemein');
        UPDATE emails SET typ = 'Direkt'
            WHERE typ NOT IN ('Privat', 'Allgemein');
        """,
    ),
]


def run(conn: sqlite3.Connection) -> None:
    applied = {row["id"] for row in conn.execute("SELECT id FROM _migrations")}
    for migration_id, sql in _MIGRATIONS:
        if migration_id in applied:
            continue
        with conn:
            conn.executescript(sql)
            conn.execute("INSERT INTO _migrations (id) VALUES (?)", (migration_id,))
