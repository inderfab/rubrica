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
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Kontakt <-> Projekt, many-to-many
CREATE TABLE IF NOT EXISTS kontakte_projekte (
    kontakt_id INTEGER NOT NULL REFERENCES kontakte(id) ON DELETE CASCADE,
    projekt_id INTEGER NOT NULL REFERENCES projekte(id) ON DELETE CASCADE,
    PRIMARY KEY (kontakt_id, projekt_id)
);

-- Vorschlaege: Review-Queue fuer Import- und (spaeter) Archivio-Treffer.
-- kontakt_id gesetzt = moeglicher Duplikat-Treffer auf bestehenden Kontakt, sonst NULL = komplett neuer Kontakt.
-- status getrennt von kontakte.status: offen | bestaetigt | abgelehnt.
-- Kein Vorschlag darf kontakte je automatisch veraendern - nur nach manueller Bestaetigung.
CREATE TABLE IF NOT EXISTS vorschlaege (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kontakt_id INTEGER REFERENCES kontakte(id) ON DELETE CASCADE,
    quelle     TEXT    NOT NULL DEFAULT 'import' CHECK (quelle IN ('import', 'archivio')),
    status     TEXT    NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'bestaetigt', 'abgelehnt')),
    rohdaten   TEXT    NOT NULL DEFAULT '{}',
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
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
