from __future__ import annotations

import sqlite3

# Reihenfolge = Anwendungsreihenfolge. Neue Migrationen unten anhaengen, bestehende nie aendern.
# Solange Rubrica noch nicht produktiv im Einsatz ist, werden Schemaaenderungen direkt in
# schema.sql gepflegt statt per Migration - vermeidet doppelte Spalten-Definitionen.
_MIGRATIONS: list[tuple[str, str]] = []


def run(conn: sqlite3.Connection) -> None:
    applied = {row["id"] for row in conn.execute("SELECT id FROM _migrations")}
    for migration_id, sql in _MIGRATIONS:
        if migration_id in applied:
            continue
        with conn:
            conn.executescript(sql)
            conn.execute("INSERT INTO _migrations (id) VALUES (?)", (migration_id,))
