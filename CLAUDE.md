# Rubrica — Zentrale Adressverwaltung

> 📌 **Vor der Arbeit lesen:** [`docs/konzept.md`](docs/konzept.md) — vollständiges technisches
> Konzept (Architektur, Datenmodell, Phasenplan, offene Punkte). Bei jeder relevanten
> Änderung/Anpassung nachführen.

## Stack
- **Backend**: Python 3.9 (Systemversion auf dem Mac Studio, kein `X | None`-Syntax in FastAPI-Routenparametern — `typing.Optional` verwenden), FastAPI
- **Datenbank**: SQLite
- **Frontend**: HTMX + Jinja2 Templates
- **Paketmanagement**: pip + requirements.txt

## Prinzipien
- Vollständig lokal — kein Cloud-Dienst, keine externe API
- Die App ist die alleinige Datenquelle ("Single Source of Truth"); Radicale/CardDAV (später) ist nur Auslieferungsschicht zu Apple Kontakte
- **Nie automatisches Überschreiben** bestehender Kontaktdaten — Treffer aus Import oder späterer Archivio-Integration erzeugen immer einen Eintrag in `vorschlaege`, der erst nach manueller Bestätigung übernommen wird

## Projektstruktur
```
rubrica/
  web/        # FastAPI-App, Routen, Jinja2-Templates
  db/         # Schema, Migrations, DB-Hilfsfunktionen
  config/     # Konfigurationslogik (lädt config.yaml)
  tests/      # pytest-Tests
```

## Datenbank
- Schema: `db/schema.sql`
- Kerntabellen: `kontakte`, `telefonnummern`, `emails`, `projekte`, `kontakte_projekte`, `vorschlaege`
- `vorschlaege.status` (offen/bestaetigt/abgelehnt) ist getrennt von `kontakte.status`

## Konventionen
- FastAPI-Routen direkt in `web/*.py` (analog zu Archivio: `contacts.py`, `projects.py`, `review.py`)
- Jinja2-Templates in `web/templates/`, statische Dateien in `web/static/`
- Konfiguration über `config.yaml`, geladen via `config/settings.py`; Datenverzeichnis über `RUBRICA_DATA_DIR` (Default `~/Library/Application Support/Rubrica/`)
- Tests mit pytest, Fixtures in `tests/conftest.py`

## Referenzprojekt
`/Users/fi/archivio` (gleicher Nutzer, gleiches Deployment-Muster: kein Docker, natives `.pkg`, launchd) dient als Vorbild für Paketierung und Projektaufbau.
