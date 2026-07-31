PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Kontakte: Kern-Entität
-- status: aktiv | inaktiv
CREATE TABLE IF NOT EXISTS kontakte (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    vorname    TEXT    NOT NULL DEFAULT '',
    nachname   TEXT    NOT NULL DEFAULT '',
    firma      TEXT    NOT NULL DEFAULT '',
    rolle      TEXT    NOT NULL DEFAULT '',
    kategorie  TEXT    NOT NULL DEFAULT '',
    notizen    TEXT    NOT NULL DEFAULT '',
    status     TEXT    NOT NULL DEFAULT 'aktiv' CHECK (status IN ('aktiv', 'inaktiv')),
    -- Stabile Apple-Kontakt-ID aus dem vCard-UID-Feld (nur bei Kontakte.app-Import gesetzt) -
    -- der zuverlaessigste Wiedererkennungs-Anker bei erneutem Import desselben Adressbuchs,
    -- siehe importer/vcard.py._finde_match_fuer_import. NULL bei manuell angelegten Kontakten.
    apple_uid  TEXT,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Telefonnummern: mehrere pro Kontakt möglich
CREATE TABLE IF NOT EXISTS telefonnummern (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kontakt_id INTEGER NOT NULL REFERENCES kontakte(id) ON DELETE CASCADE,
    typ        TEXT    NOT NULL DEFAULT 'mobil',
    nummer     TEXT    NOT NULL
);

-- E-Mail-Adressen: mehrere pro Kontakt möglich
CREATE TABLE IF NOT EXISTS emails (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kontakt_id INTEGER NOT NULL REFERENCES kontakte(id) ON DELETE CASCADE,
    typ        TEXT    NOT NULL DEFAULT 'arbeit',
    email      TEXT    NOT NULL
);

-- Postadressen: mehrere pro Kontakt moeglich (typ z.B. arbeit/privat/andere, aus vCard ADR-Label)
CREATE TABLE IF NOT EXISTS adressen (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kontakt_id INTEGER NOT NULL REFERENCES kontakte(id) ON DELETE CASCADE,
    typ        TEXT    NOT NULL DEFAULT 'arbeit',
    strasse    TEXT    NOT NULL DEFAULT '',
    plz        TEXT    NOT NULL DEFAULT '',
    ort        TEXT    NOT NULL DEFAULT '',
    region     TEXT    NOT NULL DEFAULT '',
    land       TEXT    NOT NULL DEFAULT ''
);

-- URLs/Homepages: mehrere pro Kontakt moeglich
CREATE TABLE IF NOT EXISTS urls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kontakt_id INTEGER NOT NULL REFERENCES kontakte(id) ON DELETE CASCADE,
    typ        TEXT    NOT NULL DEFAULT 'homepage',
    url        TEXT    NOT NULL
);

-- Projekte, denen Kontakte zugeordnet werden (spaeter als Apple-Kontaktgruppe ausgeliefert)
CREATE TABLE IF NOT EXISTS projekte (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    -- Stabile Apple-Gruppen-ID (vCard-UID der Gruppe, nur bei Kontakte.app-Import
    -- gesetzt) - ein in Rubrica umbenannter Ordner wird beim naechsten Import trotzdem
    -- richtig wiedererkannt, siehe queries.get_or_create_projekt_von_apple_gruppe.
    apple_gruppe_uid TEXT,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Kontakt <-> Projekt, many-to-many
CREATE TABLE IF NOT EXISTS kontakte_projekte (
    kontakt_id INTEGER NOT NULL REFERENCES kontakte(id) ON DELETE CASCADE,
    projekt_id INTEGER NOT NULL REFERENCES projekte(id) ON DELETE CASCADE,
    PRIMARY KEY (kontakt_id, projekt_id)
);

-- Vorschlaege: interner Zwischenschritt fuer Import- und Archivio-Treffer, wird sofort
-- bestaetigt (keine Review-Queue mehr, siehe docs/konzept.md 2026-07-14) - dient danach
-- nur noch der Nachvollziehbarkeit und der Dublettenerkennung (Archivio). Ausnahme quelle IN
-- ('mail', 'kontakte_app') (siehe mail_intake.py / kontakte_app_intake.py): bleibt bewusst
-- auf 'offen' stehen, bis im Buero manuell bestaetigt wird (web/vorschlaege.py) - ein von
-- aussen erreichbares Postfach bzw. eine direkt in Kontakte.app angelegte vCard sind ein
-- weniger vertrauenswuerdiger Kanal als ein Import/eine Archivio-Mail, die vom
-- Buero-Rechner selbst ausgehen.
-- kontakt_id gesetzt = moeglicher Duplikat-Treffer auf bestehenden Kontakt, sonst NULL = komplett neuer Kontakt.
-- status getrennt von kontakte.status: offen | bestaetigt | abgelehnt.
-- Kein Vorschlag darf kontakte je destruktiv veraendern - queries.merge_kontakt ergaenzt nur.
-- message_id: fuer quelle='mail' die Message-ID, fuer quelle='kontakte_app' der Radicale-
-- Ressourcenname (Praefix "kontakte-app:") - jeweils Dublettenschutz gegen erneutes Verarbeiten.
CREATE TABLE IF NOT EXISTS vorschlaege (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kontakt_id INTEGER REFERENCES kontakte(id) ON DELETE CASCADE,
    quelle     TEXT    NOT NULL DEFAULT 'import' CHECK (quelle IN ('import', 'archivio', 'mail', 'kontakte_app')),
    status     TEXT    NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'bestaetigt', 'abgelehnt')),
    rohdaten   TEXT    NOT NULL DEFAULT '{}',
    message_id TEXT,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Postfach -> Ordner-Zuordnung fuer die Archivio-Signatur-Anbindung: markiert gefundene
-- Kontakte aus Mails eines bestimmten Postfachs automatisch mit dem zugeordneten Ordner vor
-- (wird beim direkten Uebernehmen im Archivio-Import gesetzt).
CREATE TABLE IF NOT EXISTS postfach_zuordnung (
    postfach   TEXT    PRIMARY KEY,
    projekt_id INTEGER REFERENCES projekte(id) ON DELETE SET NULL
);

-- Migrations-Tabelle
CREATE TABLE IF NOT EXISTS _migrations (
    id         TEXT PRIMARY KEY,
    applied_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_telefonnummern_kontakt  ON telefonnummern(kontakt_id);
CREATE INDEX IF NOT EXISTS idx_emails_kontakt          ON emails(kontakt_id);
CREATE INDEX IF NOT EXISTS idx_adressen_kontakt        ON adressen(kontakt_id);
CREATE INDEX IF NOT EXISTS idx_urls_kontakt            ON urls(kontakt_id);
CREATE INDEX IF NOT EXISTS idx_kontakte_projekte_proj  ON kontakte_projekte(projekt_id);
CREATE INDEX IF NOT EXISTS idx_vorschlaege_status      ON vorschlaege(status);
CREATE INDEX IF NOT EXISTS idx_kontakte_nachname       ON kontakte(nachname);
-- idx_kontakte_apple_uid wird bewusst NICHT hier angelegt, sondern erst in der
-- Migration _kontakte_apple_uid (db/migrations.py): init_schema() fuehrt dieses
-- schema.sql IMMER zuerst aus, auch gegen eine bereits bestehende Installation, bei
-- der die Spalte "kontakte.apple_uid" noch fehlt (CREATE TABLE IF NOT EXISTS ist dort
-- ein no-op) - ein Index auf eine zu diesem Zeitpunkt noch nicht existierende Spalte
-- liess den Server beim Start mit "no such column: apple_uid" abstuerzen, bevor die
-- nachfolgende Migration die Spalte ueberhaupt ergaenzen konnte.
