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
        -- Allgemein (die Kategorien von damals; heute config/settings.py bzw.
        -- /einstellungen/kategorien). Mobile Nummern
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
    (
        "2026-07-28_vorschlaege_mail_quelle",
        """
        -- SQLite kennt kein ALTER TABLE fuer CHECK-Constraints - Tabelle neu anlegen,
        -- Daten uebernehmen. Fuegt 'mail' als erlaubte quelle hinzu (Mail-Eingang,
        -- siehe mail_intake.py) und eine message_id-Spalte fuer deren Dublettenschutz.
        ALTER TABLE vorschlaege RENAME TO vorschlaege_alt_2026_07_28;

        CREATE TABLE vorschlaege (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            kontakt_id INTEGER REFERENCES kontakte(id) ON DELETE CASCADE,
            quelle     TEXT    NOT NULL DEFAULT 'import' CHECK (quelle IN ('import', 'archivio', 'mail')),
            status     TEXT    NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'bestaetigt', 'abgelehnt')),
            rohdaten   TEXT    NOT NULL DEFAULT '{}',
            message_id TEXT,
            created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

        INSERT INTO vorschlaege (id, kontakt_id, quelle, status, rohdaten, created_at)
            SELECT id, kontakt_id, quelle, status, rohdaten, created_at FROM vorschlaege_alt_2026_07_28;

        DROP TABLE vorschlaege_alt_2026_07_28;
        """,
    ),
    (
        "2026-07-31_vorschlaege_kontakte_app_quelle",
        """
        -- Fuegt 'kontakte_app' als erlaubte quelle hinzu - dritte Erfassungs-Quelle neben
        -- manueller Neuanlage und Mail-Eingang: Kontakte, die direkt in Kontakte.app angelegt
        -- wurden, werden ueber CardDAV erkannt (siehe kontakte_app_intake.py) und landen hier
        -- als Vorschlag statt automatisch uebernommen zu werden.
        ALTER TABLE vorschlaege RENAME TO vorschlaege_alt_2026_07_31;

        CREATE TABLE vorschlaege (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            kontakt_id INTEGER REFERENCES kontakte(id) ON DELETE CASCADE,
            quelle     TEXT    NOT NULL DEFAULT 'import' CHECK (quelle IN ('import', 'archivio', 'mail', 'kontakte_app')),
            status     TEXT    NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'bestaetigt', 'abgelehnt')),
            rohdaten   TEXT    NOT NULL DEFAULT '{}',
            message_id TEXT,
            created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

        INSERT INTO vorschlaege (id, kontakt_id, quelle, status, rohdaten, message_id, created_at)
            SELECT id, kontakt_id, quelle, status, rohdaten, message_id, created_at FROM vorschlaege_alt_2026_07_31;

        DROP TABLE vorschlaege_alt_2026_07_31;
        """,
    ),
    (
        "2026-08-06_feste_telefon_email_kategorien",
        """
        -- Nutzer-Meldung: "zurzeit ist es ein riesiges durcheinander und jedes mal wenn
        -- man neue nummern eingibt kann man wieder frei irgendwelche Optionen wählen."
        -- Die Auswahl bot bisher zusaetzlich alle im Bestand vorkommenden Werte an und
        -- hielt den Wildwuchs damit am Leben. Ab jetzt sind die Listen fest
        -- (web/contacts.py: TELEFON_TYPEN / EMAIL_TYPEN); dieser Schritt bildet den
        -- Altbestand darauf ab.
        --
        -- Handy-Erkennung vor der Grobzuordnung, sonst wuerde "cell"/"mobil" schon von
        -- der Privat-Regel eingefangen. Schweizer Mobilvorwahlen (+41 7x / 07x) gelten
        -- als Handy, wenn kein Label etwas anderes sagt. Fehlzuordnungen sind bewusst in
        -- Kauf genommen und lassen sich einzeln korrigieren (Nutzer-Vorgabe).
        UPDATE telefonnummern SET typ = 'Privat Handy'
            WHERE lower(typ) IN ('privat handy', 'handy privat', 'mobil privat', 'privatmobil');
        UPDATE telefonnummern SET typ = 'Direkt Handy'
            WHERE lower(typ) IN ('cell', 'mobil', 'mobile', 'iphone', 'handy', 'natel', 'direkt handy');
        UPDATE telefonnummern SET typ = 'Privat'
            WHERE lower(typ) IN ('home', 'privat', 'private', 'zuhause');
        -- Alles Uebrige (arbeit/work/main/allgemein/Freitext/leer) wird geschaeftlich.
        UPDATE telefonnummern SET typ = 'Direkt'
            WHERE typ NOT IN ('Direkt', 'Direkt Handy', 'Privat', 'Privat Handy');
        -- Nachlauf: als Privat markierte Schweizer Mobilnummern sauber als Handy fuehren.
        UPDATE telefonnummern SET typ = 'Privat Handy'
            WHERE typ = 'Privat' AND (
                replace(replace(nummer, ' ', ''), '-', '') LIKE '+417%'
                OR replace(replace(nummer, ' ', ''), '-', '') LIKE '07%');

        UPDATE emails SET typ = 'Privat'
            WHERE lower(typ) IN ('home', 'privat', 'private');
        UPDATE emails SET typ = 'Allgemein'
            WHERE lower(typ) IN ('main', 'allgemein', 'info', 'general');
        UPDATE emails SET typ = 'Direkt'
            WHERE typ NOT IN ('Direkt', 'Allgemein', 'Privat');
        """,
    ),
    (
        "2026-08-07_keine_kontakt_loeschvorschlaege_mehr",
        """
        -- Nutzer-Entscheid nach dem Abnahmetest: Kontakte loeschen geht nur noch im
        -- Browser; eine Loeschung in Kontakte.app wird zurueckgeschrieben. Der Typ
        -- "loeschung" entsteht damit nicht mehr - bereits offene Vorschlaege dieser
        -- Art muessen weg, sonst stehen sie ohne passende Darstellung in der Liste
        -- und "Uebernehmen" liefe in den falschen Zweig (Kontakt neu anlegen).
        -- Ordner-Loeschungen bleiben unberuehrt.
        UPDATE vorschlaege SET status = 'abgelehnt'
            WHERE status = 'offen' AND message_id LIKE 'kontakte-app-loeschung:%';
        """,
    ),
    (
        "2026-08-07_keine_ordner_loeschvorschlaege_mehr",
        """
        -- Nachtrag zum Entscheid oben: er gilt auch fuer Ordner ("wenn man lokal
        -- loescht soll es diese aenderung nie annehmen"). Eine in Kontakte.app
        -- geloeschte Gruppe wird zurueckgeschrieben, nicht vorgelegt.
        UPDATE vorschlaege SET status = 'abgelehnt'
            WHERE status = 'offen' AND message_id LIKE 'kontakte-app-ordner-loeschung:%';
        """,
    ),
]


def _kontakte_apple_uid(conn: sqlite3.Connection) -> None:
    """Stabile Apple-Kontakt-ID (vCard-UID) fuer zuverlaessiges Wiedererkennen bei
    erneutem Kontakte.app-Import - siehe importer/vcard.py._finde_match_fuer_import.
    Regression: zwei verschiedene Personen mit gemeinsamem Festnetzanschluss wurden
    zuvor ueber den Telefon-Abgleich faelschlich als derselbe Kontakt erkannt und
    automatisch (ohne Rueckfrage) zusammengefuehrt. Als Funktion statt reinem SQL-
    String, da schema.sql fuer frische Installationen die Spalte bereits enthaelt -
    ein blindes ALTER TABLE ADD COLUMN wuerde dort mit "duplicate column name" fehlschlagen."""
    spalten = {row["name"] for row in conn.execute("PRAGMA table_info(kontakte)")}
    if "apple_uid" not in spalten:
        conn.execute("ALTER TABLE kontakte ADD COLUMN apple_uid TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kontakte_apple_uid ON kontakte(apple_uid)")


def _projekte_apple_gruppe_uid(conn: sqlite3.Connection) -> None:
    """Stabile Apple-Gruppen-ID fuer zuverlaessiges Wiedererkennen von Ordnern bei
    erneutem Kontakte.app-Import, auch wenn der Ordner in Rubrica zwischenzeitlich
    umbenannt wurde - siehe queries.get_or_create_projekt_von_apple_gruppe. Ohne das
    wuerde ein Re-Import den alten Apple-Gruppennamen als NEUEN Ordner wiederanlegen,
    da die Zuordnung bisher rein ueber den (jetzt geaenderten) Namen lief. Gleiches
    Guard-Muster wie _kontakte_apple_uid (schema.sql hat die Spalte bei frischen
    Installationen schon, ein blindes ALTER TABLE wuerde dort fehlschlagen)."""
    spalten = {row["name"] for row in conn.execute("PRAGMA table_info(projekte)")}
    if "apple_gruppe_uid" not in spalten:
        conn.execute("ALTER TABLE projekte ADD COLUMN apple_gruppe_uid TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projekte_apple_gruppe_uid ON projekte(apple_gruppe_uid)")


def _projekte_zuletzt_gepushte_mitglieder(conn: sqlite3.Connection) -> None:
    """Referenzpunkt fuer den Mitgliedschafts-Abgleich mit Kontakte.app: haelt fest,
    welche Mitglieder Rubrica beim letzten Push selbst in die Gruppen-vCard
    geschrieben hat (siehe sync/radicale.py::push_projekt). Nur damit laesst sich
    eine in Kontakte.app entfernte Mitgliedschaft von einem fehlgeschlagenen
    eigenen Push unterscheiden - ohne diese Unterscheidung wuerde Rubrica bei einem
    Push-Fehler gueltige Zuordnungen loeschen. Bestehende Ordner starten mit NULL
    und werden erst nach ihrem naechsten Push abgeglichen (bewusst: fuer die
    Vergangenheit gibt es keinen verlaesslichen Referenzpunkt). Gleiches
    Guard-Muster wie _projekte_apple_gruppe_uid - schema.sql enthaelt die Spalte
    fuer frische Installationen bereits."""
    spalten = {row["name"] for row in conn.execute("PRAGMA table_info(projekte)")}
    if "zuletzt_gepushte_mitglieder" not in spalten:
        conn.execute("ALTER TABLE projekte ADD COLUMN zuletzt_gepushte_mitglieder TEXT")


def _kontakte_zuletzt_gepushte_vcard(conn: sqlite3.Connection) -> None:
    """Referenzpunkt fuer die Erkennung von Feldaenderungen aus Kontakte.app: haelt
    die vCard fest, die Rubrica beim letzten Push selbst geschrieben hat (siehe
    sync/radicale.py::push_kontakt). Bestehende Kontakte starten mit NULL und werden
    erst nach ihrem naechsten Push ueberwacht - fuer die Vergangenheit gibt es keinen
    verlaesslichen Vergleichsstand. Gleiches Guard-Muster wie _kontakte_apple_uid."""
    spalten = {row["name"] for row in conn.execute("PRAGMA table_info(kontakte)")}
    if "zuletzt_gepushte_vcard" not in spalten:
        conn.execute("ALTER TABLE kontakte ADD COLUMN zuletzt_gepushte_vcard TEXT")


_PYTHON_MIGRATIONEN: list[tuple[str, "callable"]] = [
    ("2026-07-30_kontakte_apple_uid", _kontakte_apple_uid),
    ("2026-07-30_projekte_apple_gruppe_uid", _projekte_apple_gruppe_uid),
    ("2026-08-04_projekte_zuletzt_gepushte_mitglieder", _projekte_zuletzt_gepushte_mitglieder),
    ("2026-08-05_kontakte_zuletzt_gepushte_vcard", _kontakte_zuletzt_gepushte_vcard),
]


def run(conn: sqlite3.Connection) -> None:
    applied = {row["id"] for row in conn.execute("SELECT id FROM _migrations")}
    for migration_id, sql in _MIGRATIONS:
        if migration_id in applied:
            continue
        with conn:
            conn.executescript(sql)
            conn.execute("INSERT INTO _migrations (id) VALUES (?)", (migration_id,))
    for migration_id, funktion in _PYTHON_MIGRATIONEN:
        if migration_id in applied:
            continue
        with conn:
            funktion(conn)
            conn.execute("INSERT INTO _migrations (id) VALUES (?)", (migration_id,))
