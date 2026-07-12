# Rubrica – Technisches Konzept

Dieses Dokument fasst das Konzept für Rubrica, eine zentrale Adressverwaltung, zusammen und dient als Grundlage für die Umsetzung (z. B. mit Claude Code). Es liegt im Repo unter `docs/konzept.md` und wird bei jeder relevanten Änderung/Anpassung nachgeführt, damit es als aktuelle Referenz für alle weiteren Entwicklungsschritte verfügbar bleibt.

Entwicklung erfolgt auf dem Mac Studio (Benutzer `fabio`), das fertige Produkt läuft produktiv auf einem iMac im Büro.

## 1. Ausgangslage

Aktuell wird das Apple Adressbuch genutzt und laufend um Fachplaner und Unternehmer ergänzt. Probleme:

- Neue Kontakte müssen manuell exportiert und bei allen Mitarbeitern importiert werden – kein echter Sync.
- Das Adressbuch ist nie vollständig, weil Mitarbeiter neue Kontakte vergessen anzulegen oder nicht teilen.
- Vorteil des aktuellen Setups, der erhalten bleiben soll: direkte Verbindung zur VOIP-Telefonapp, Klickwahl ohne Kopieren.

## 2. Ziele

1. Zentrale, für alle Stationen automatisch synchronisierte Adressverwaltung.
2. Eingabe/Änderung von jeder Station aus möglich.
3. Automatische Erkennung neuer Adressen aus E-Mails (über Archivio), aber **nie automatisches Überschreiben** bestehender Daten – Vorschläge müssen manuell bestätigt werden.
4. Export als Excel und PDF.
5. Telefonnummern weiterhin per Klick über die VOIP-App wählbar, ohne Copy-Paste.
6. Kontakte können einem oder mehreren Ordnern zugewiesen werden, sichtbar als Gruppen im Apple Adressbuch.
7. Bestehendes Apple Adressbuch (inkl. mehrerer, teils überlappender Mitarbeiter-Kopien) als Grundlage importierbar.

## 3. Architekturübersicht

Kernprinzip: Die selbst gebaute App ist die alleinige Datenquelle ("Single Source of Truth"). Ein selbst gehosteter CardDAV-Server (Radicale) ist nur die Auslieferungsschicht zu Apple Kontakte – kein zweites System, das synchron gehalten werden muss.

```mermaid
flowchart TB
    A[Bestehendes Adressbuch<br/>vCard-Export] --> D
    B[Web-UI<br/>alle Stationen] --> D
    C[Archivio: Freitext-Extraktion<br/>Phase 4, später] -.-> M[Matching-Engine<br/>Phase 4, später]
    M -.-> RQ[Review-Queue]
    RQ -->|manuell bestätigt| D[(Zentrale DB<br/>Custom App)]
    D --> R[Radicale<br/>CardDAV-Server]
    R --> K[Apple Kontakte<br/>alle Stationen]
    K --> V[VOIP-Klickwahl]
    D --> E[Export<br/>Excel / PDF]
```

Deployment: kein Docker. Die App läuft als natives, über ein `.pkg` installiertes Programm auf einem iMac im Büro – gleiches Vorgehen wie bei Archivio. Python-Interpreter und alle Abhängigkeiten (FastAPI, Radicale, etc.) werden vollständig ins Paket gebündelt, sodass keine separate Python-Installation nötig ist. Backend-App und Radicale laufen als zwei launchd-Dienste (`LaunchDaemons`), die beim Systemstart automatisch starten. Andere Stationen greifen rein lokal über das Büro-LAN zu (Web-UI per Browser, CardDAV-Account in Kontakte.app), z. B. über den Bonjour-Hostnamen des iMacs (`<name>.local`) – keine externe Erreichbarkeit nötig.

Claude Code sollte sich für den Paketierungs-Ansatz (pkg-Build, launchd-Plists, Bibliothekspfade) am bestehenden Code von Archivio orientieren, der unter `/Users/fi/archivio` liegt, damit beide Tools demselben Muster folgen.

## 4. Datenmodell

```mermaid
erDiagram
    KONTAKTE ||--o{ TELEFONNUMMERN : hat
    KONTAKTE ||--o{ EMAILS : hat
    KONTAKTE }o--o{ PROJEKTE : zugeordnet
    KONTAKTE ||--o{ VORSCHLAEGE : quelle
    KONTAKTE ||--o{ ADRESSEN : hat
    KONTAKTE ||--o{ URLS : hat
    KONTAKTE {
        uuid id PK
        string vorname
        string nachname
        string firma
        string rolle
        string kategorie
        string notizen
        string status
        datetime created_at
        datetime updated_at
    }
    TELEFONNUMMERN {
        uuid id PK
        uuid kontakt_id FK
        string typ
        string nummer
    }
    EMAILS {
        uuid id PK
        uuid kontakt_id FK
        string typ
        string email
    }
    ADRESSEN {
        uuid id PK
        uuid kontakt_id FK
        string typ
        string strasse
        string plz
        string ort
        string region
        string land
    }
    URLS {
        uuid id PK
        uuid kontakt_id FK
        string typ
        string url
    }
    PROJEKTE {
        uuid id PK
        string name
    }
    VORSCHLAEGE {
        uuid id PK
        uuid kontakt_id FK
        string quelle
        string status
        json rohdaten
    }
```

Wichtig: `VORSCHLAEGE.status` (offen / bestätigt / abgelehnt) ist getrennt von `KONTAKTE.status`. Ein Treffer aus Archivio oder aus dem Import verändert nie direkt einen bestehenden Kontakt, sondern erzeugt einen Eintrag in `VORSCHLAEGE`, der erst nach manueller Bestätigung übernommen wird.

Feldumfang bewusst an der tatsächlichen Nutzung im bestehenden Apple-Adressbuch ausgerichtet (Stichprobe 1538 Kontakte, Stand 22.06.2026): Telefon/E-Mail (fast durchgängig genutzt), Postadresse (1417), Notizen (755) und Homepage/URL (559) sind abgedeckt. Selten genutzte Apple-Felder (Geburtstag, Spitzname, Social-Profile, Instant-Messenger, verwandte Namen — je unter 1.3 % der Kontakte) werden bewusst nicht abgebildet, um das Datenmodell schlank zu halten; bei Bedarf später einfach ergänzbar.

## 5. Komponenten im Detail

### 5.1 Zentrale App (Backend + Web-UI)
- Verwaltet CRUD auf Kontakte (inkl. Telefonnummern, E-Mails, Adressen, URLs, Notizen), Ordner.
- **Bewusst keine Funktion zum Neuanlegen von Kontakten in der App.** Neue Kontakte entstehen weiterhin in Kontakte.app (gewohntes Tool, volle Apple-Feldpalette) und kommen ausschliesslich über den Import (siehe 5.6) in die App. Die Web-UI dient dem Bearbeiten bestehender Kontakte (Rubrica-eigene Felder wie Kategorie/Ordner-Zuordnung, Korrekturen an importierten Daten).
- Stellt die Review-Queue als UI bereit (offene Vorschläge bestätigen/ablehnen/zusammenführen).
- **Push-Sync nach Radicale** (`sync/radicale.py`): bei jeder Kontakt-Änderung/-Löschung, Ordner-Zuordnung
  oder Vorschlag-Bestätigung schreibt die App die betroffene(n) vCard(s) per CardDAV `PUT` (Legt die
  Adressbuch-Collection bei Bedarf automatisch per `MKCOL` an). Deterministisches UID-Schema:
  `kontakt-{id}` / `projekt-{id}`, keine zusätzliche Spalte nötig. Konfigurierbar über `radicale.*` in
  `config.yaml`, standardmässig deaktiviert (`enabled: false`) — ohne Konfiguration bleibt die App voll
  funktionsfähig, Sync-Fehler (Radicale nicht erreichbar) werden geloggt, nie als Fehler an die Web-UI
  durchgereicht.

### 5.2 CardDAV-Layer (Radicale)
- Leichtgewichtiger, dateibasierter CardDAV-Server, für 6–15 Nutzer ausreichend dimensioniert.
- Wird als Python-Abhängigkeit ins `.pkg` gebündelt und läuft als eigener launchd-Dienst neben dem Backend; wird von der App beschrieben (App schreibt, Radicale liefert nur aus).
- ~~**Kritischer Punkt – zuerst testen:**~~ **Erledigt (2026-07-10):** Apple hält sich bei Kontaktgruppen nicht an den offiziellen vCard4-Standard (`KIND:group`/`MEMBER`), sondern nutzt proprietäre Properties (`X-ADDRESSBOOKSERVER-KIND`, `X-ADDRESSBOOKSERVER-MEMBER`) — per Spike auf einem iPhone verifiziert, Gruppe erscheint korrekt mit Mitgliedern (siehe Abschnitt 9).
- **Wichtiger Praxis-Befund aus dem Spike:** macOS/iOS Kontakte.app führt bei manuellem CardDAV-Setup ("Erweitert") immer eine HTTPS-Autodiscovery auf den Ports 8443/8843/443 durch, unabhängig vom eingetragenen Port. Radicale muss daher HTTPS auf einem dieser Ports anbieten (Dev: selbstsigniertes Zertifikat, automatisch von `scripts/radicale-dev.sh` erzeugt; Produktivbetrieb: siehe Abschnitt 7).
- Auth: `htpasswd` mit bcrypt (`config/radicale.conf.example`), Passwort setzen via `scripts/radicale_set_password.py <user> <passwort>`.

### 5.3 Datenablage
- Konfiguration und SQLite-DB liegen unter `~/Library/Application Support/Rubrica/` (analog zum Archivio-Vorgehen, Pfad steuerbar über `RUBRICA_DATA_DIR`).
- Radicales vCard-Speicher liegt als Unterordner im selben Application-Support-Verzeichnis, damit ein Backup des gesamten Ordners reicht, um alles zu sichern.

### 5.4 Ordner-Zuordnung
- Nutzerseitig "Ordner" genannt, intern weiterhin `KONTAKTE ↔ PROJEKTE` als many-to-many (Tabellen-/Schema-Name bewusst unverändert, siehe unten) — ein Kontakt kann mehreren Ordnern zugeordnet sein.
- Pro Ordner erzeugt die App eine Gruppen-vCard in Radicale (siehe 5.2/5.1), die als Apple-Kontaktgruppe mit Ordnername erscheint. Bei jeder Änderung der Zuordnung (Kontakt bearbeitet, gelöscht, Vorschlag bestätigt) werden sowohl der alte als auch der neue Ordner neu geschrieben, damit Mitglieder korrekt hinzugefügt/entfernt werden.

### 5.5 Archivio-Integration (zurückgestellt auf Phase 4, siehe Abschnitt 8)
- **Wichtig:** Es gibt aktuell noch keine SQL-DB mit fertig strukturierten Adressdaten. Archivio scannt Dokumente auf dem Server sowie E-Mails im Postfach und extrahiert deren Inhalt als Rohtext in eine SQL-DB. Adressdaten sind darin also nicht als eigene Felder vorhanden, sondern höchstens innerhalb des extrahierten Fließtexts auffindbar – z. B. in einer E-Mail-Signatur.
- Das bedeutet: Bevor eine Matching-Engine gebaut werden kann, braucht es zusätzlich eine Extraktionslogik (Erkennung von Name/Firma/Telefon/E-Mail innerhalb von Freitext, z. B. Signaturen). Das ist ein eigenständiges, nicht triviales Teilproblem.
- Dieser Teil ist bewusst kein Bestandteil der ersten Umsetzung, sondern wird erst angegangen, wenn Phase 1–2 stehen. Der bestehende Archivio-Code liegt unter `/Users/fi/archivio` und sollte zu gegebener Zeit als Referenz für das tatsächliche SQL-Schema herangezogen werden, bevor die Extraktions- und Matching-Logik entworfen wird.
- Grundprinzip bleibt aber von Anfang an gültig und sollte im Datenmodell (Tabelle `VORSCHLAEGE`) schon vorgesehen sein: kein Treffer → neuer Vorschlag in der Review-Queue; Treffer mit abweichenden Daten → Änderungsvorschlag, nie automatische Änderung.

### 5.6 Import bestehender Adressbücher — dauerhafter Eingabeweg, nicht nur Einmal-Migration
- Export als `.vcf` aus Kontakte.app (Ablage → Exportieren → vCard exportieren) bei jedem Mitarbeiter. Sowohl Einzel-Export (ein Kontakt) als auch Batch-Export (alle/mehrere Kontakte in einer Datei) werden unterstützt; mehrere Dateien gleichzeitig hochladbar.
- **Das bleibt dauerhaft der einzige Weg, Kontakte anzulegen/zu aktualisieren — nicht nur für die initiale Migration.** Grund: eine echte bidirektionale CardDAV-Synchronisation (Kontakte.app ↔ App) würde das Kernprinzip "nie automatisches Überschreiben" aushebeln, weil Änderungen aus Kontakte.app dann ungeprüft durchschlagen würden. Auch nach Phase 2 bleibt Radicale nur Ausgaberichtung (App → Apple Kontakte für Klickwahl); die Rückrichtung bleibt bewusst Export → Import → Review-Queue.
- Import-Parser mappt vCard-Felder auf das Datenmodell: Name, Firma, Rolle, Telefonnummern, E-Mails, Postadressen (ADR), Homepage/URLs, Notizen (NOTE).
- Da mehrere, teils überlappende Mitarbeiter-Kopien existieren: alle Exporte importieren und dieselbe Review-Queue-Logik (siehe `VORSCHLAEGE`-Tabelle) für die Dedup-/Zusammenführung nutzen – keine zweite Logik nötig, auch nicht für die spätere Archivio-Integration. Matching-Reihenfolge: exakte E-Mail → normalisierte Telefonnummer → exakter Vor-/Nachname.
- Bestehende lokale Gruppen aus dem Import können optional als erste Ordner übernommen werden (Apple-Gruppen-vCards mit `X-ADDRESSBOOKSERVER-KIND`/`MEMBER`, in der Praxis am bestehenden Adressbuch verifiziert: ~32 Gruppen bei 1538 Kontakten).

### 5.7 Export
- Excel- und PDF-Export direkt aus der zentralen DB, bei Bedarf gefiltert nach Ordner/Kategorie.

## 6. Vorgeschlagener Tech-Stack

| Bereich | Empfehlung | Begründung |
|---|---|---|
| Backend | Python + FastAPI | Gleiche Sprache wie Radicale, gut dokumentiert, KI-Coding-freundlich |
| Datenbank | SQLite | Datenmenge ist klein (Kontaktliste), keine separate DB-Infrastruktur nötig, einfache Backups. Bei Bedarf später auf Postgres migrierbar |
| Frontend | Server-seitig gerendert (Jinja2 + htmx) | Keine npm-Build-Pipeline nötig, für einen Solo-Entwickler mit KI-Unterstützung deutlich einfacher zu warten als eine SPA |
| CardDAV | Radicale | Siehe 5.2, als Python-Abhängigkeit gebündelt |
| Paketierung | `.pkg`-Installer, launchd-Dienste | Gleiches Vorgehen wie bei Archivio, kein Docker, läuft nativ auf dem iMac |
| Datenablage | `~/Library/Application Support/Rubrica/` | Konfiguration und SQLite-DB an einem Ort, einfaches Backup |
| Versionierung | Git, Remote auf GitHub | Wie gewünscht |

Dies ist ein Startvorschlag – bei Bedarf anpassbar, insbesondere falls beim Bauen mit Claude Code eine andere Sprache bevorzugt wird.

## 7. Zugriff & Sicherheit

Geklärt: Zugriff erfolgt vorerst ausschließlich lokal im Büro-LAN, kein Remote-Zugriff nötig. Web-UI weiterhin per einfachem HTTP im lokalen Netz erreichbar (`<name>.local`), kein Reverse-Proxy nötig.

**Revidiert durch Phase-2-Spike-Erfahrung:** Für CardDAV (Radicale) ist HTTPS entgegen der ursprünglichen Annahme doch nötig — macOS/iOS Kontakte.app führt beim Account-Setup immer eine HTTPS-Autodiscovery durch (siehe Abschnitt 5.2/9), unabhängig von der eigentlichen LAN-only-Anforderung. Für den Produktivbetrieb auf dem iMac:
- **Auth**: `htpasswd`/bcrypt (siehe 5.2) statt der im Spike genutzten `auth.type=none`.
- **TLS-Zertifikat**: Dev nutzt ein selbstsigniertes Zertifikat (pro Gerät manuell als vertrauenswürdig bestätigen). Für den echten Rollout auf mehreren Stationen sollte ein einmal erzeugtes, auf allen Stationen als vertrauenswürdig hinterlegtes Zertifikat verwendet werden (z. B. eigene lokale CA à la `mkcert`), damit nicht jede Station einzeln den "nicht vertrauenswürdig"-Dialog bestätigen muss. Das ist ein offener Punkt für die Rollout-Phase, noch nicht umgesetzt.

## 8. Phasenplan

| Phase | Inhalt |
|---|---|
| 0 | Import bestehender Adressbücher (alle Mitarbeiter-Exporte) + Dedup über Review-Queue |
| 1 | Zentrale DB + Web-UI für manuelle Eingabe (löst das Kernproblem bereits) |
| 2 | Radicale-Anbindung inkl. Apple-Gruppen-Spike – **zuerst isoliert testen**, bevor der Rest darauf aufbaut |
| 3 | Export-Funktionen (Excel/PDF) |
| 4 *(zurückgestellt)* | Archivio-Integration: zunächst Schema-Sichtung + Extraktionslogik für Adressdaten aus Freitext, danach Matching-Engine. Startet erst, wenn Phase 1–3 stehen und Archivios SQL-Schema bekannt ist |

## 9. Offene Punkte / Risiken

- ~~Apple-Gruppen-Kompatibilität (proprietäres vCard-Format) – größtes technisches Risiko, früh verifizieren.~~
  **GELÖST (2026-07-10).** Radicale (3.7.6, läuft unter Python 3.9) verarbeitet und liefert eine
  Gruppen-vCard (`X-ADDRESSBOOKSERVER-KIND:group` + `-MEMBER:urn:uuid:...`) über CardDAV korrekt aus
  (`MKCOL`/`PUT`/`GET`/`PROPFIND` per curl verifiziert). **Auf einem iPhone als CardDAV-Account
  eingerichtet erscheint die Gruppe "Rubrica Testprojekt" korrekt mit den zugehörigen Testkontakten
  als Mitglieder** — das Kernrisiko ist damit ausgeräumt.
- ~~macOS Kontakte.app holt nach dem Verbinden nie die Kontaktdaten ab (nur Discovery, nie `REPORT`) –
  eingeordnet als macOS-Einschränkung.~~ **URSACHE GEFUNDEN & GELÖST (2026-07-10). War kein macOS-Bug,
  sondern ein nicht-konformes TLS-Zertifikat.** Symptom: macOS Kontakte.app (Sonoma 14.8.2) machte nach
  dem Verbinden nur Discovery (`PROPFIND`/`OPTIONS`), nie einen `REPORT`; die Kontakte blieben leer, teils
  Meldung "Accountname/Passwort konnte nicht überprüft werden". iOS funktionierte, weil man dort das
  Zertifikat per Dialog **manuell** bestätigt (Trust-Override) — der macOS-Sync-Daemon
  (`dataaccessd`/`contactsd`) validiert dagegen strikt und bricht **vor** dem `REPORT` still ab.
  - **Beleg (Unified Log, `trustd`):** `[com.apple.securityd:ev] Leaf has invalid basic constraints`.
  - **Ursache im Detail:** Das selbstsignierte Zertifikat aus dem alten Build-Skript
    (`openssl req -x509 -days 3650`, nur `subjectAltName`) verletzte gleich mehrere Apple-Anforderungen an
    TLS-Server-Zertifikate: (a) **keine `basicConstraints`** → ein Zertifikat, das zugleich eigener
    Trust-Anchor und Server-Leaf ist, scheitert an Apples Constraint-Prüfung; (b) **kein
    `extendedKeyUsage=serverAuth`**; (c) **Gültigkeit 3650 Tage** statt der von Apple erzwungenen
    **≤ 398 Tage** (support.apple.com/en-us/HT211025).
  - **Lösung:** neues `scripts/generate-cert.sh` erzeugt eine lokale **CA** + davon signiertes **Leaf**
    (`CA:FALSE`, `keyUsage=digitalSignature,keyEncipherment`, `extendedKeyUsage=serverAuth`, SAN mit
    Hostname, 397 Tage, SHA-256/RSA-2048) — dasselbe Prinzip wie `mkcert`. Radicale liefert die Full-Chain
    (Leaf + CA) aus; die CA wird auf jedem Client **einmalig** als vertrauenswürdig markiert. Der
    `.pkg`-Postinstall (`scripts/build-pkg.sh`) erzeugt das Zertifikat und markiert die CA per
    `security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain` automatisch als
    vertrauenswürdig (läuft als root → kein Dialog). Vorteil des CA-Modells: Das jährlich ablaufende Leaf
    (398-Tage-Grenze) kann erneuert werden, ohne dass auf den Clients erneut vertraut werden muss.
  - **Manuell (bestehende Installation ohne neuen Postinstall, z. B. Mac Studio):** einmalig
    `sudo security add-trusted-cert -d -r trustRoot -p ssl -k /Library/Keychains/System.keychain \
    "~/Library/Application Support/Rubrica/radicale-tls/ca-cert.pem"`, danach alten CardDAV-Account
    entfernen und neu anlegen.
  - **Zu beachten beim "Erweitert"-CardDAV-Setup:** macOS prüft bei der Accountverifizierung immer HTTPS
    auf 8443/8843/443, unabhängig vom eingetragenen Port (s. `config/radicale.conf.example`).
- ~~macOS Kontakte.app synchronisiert nach behobenem TLS zwar fehlerfrei die Discovery, startet aber den
  eigentlichen Inhalts-Sync nicht.~~ **GELÖST (2026-07-12).** War ein macOS-Client-Zustandsproblem, kein
  Rubrica-/Radicale-Fehler — durch Vanilla-Radicale-Gegentest zweifelsfrei von Rubrica getrennt (siehe unten).
  - **Beweis, dass Rubrica nicht die Ursache war:** (a) iOS synchronisiert mit identischen Serverantworten
    zuverlässig; (b) ein frisches, leeres Vanilla-Radicale (kein Rubrica-Code, nur 2 Testkontakte) zeigte
    exakt dasselbe Symptom — Discovery ja, `REPORT` nie; (c) per mitschreibendem TLS-Proxy verifiziert, dass
    macOS die von ChatGPT vermuteten Properties (`getcontenttype`/`getcontentlength` auf der Collection)
    nie abfragt — diese Hypothese war falsch.
  - **Tatsächliche Ursache:** angesammelter Client-Zustand nach mehreren Setup-Versuchen (8 verwaiste, leere
    CardDAV-Quellen unter `~/Library/Application Support/AddressBook/Sources/`) **plus** Account-Setup im
    Modus **"Erweitert" mit explizitem Serverpfad** (`/fi/kontakte/`) — das führte dazu, dass `contactsd`
    nach der Discovery keinen Inhalts-Sync ansetzte.
  - **Lösung:** (1) Account entfernen, Kontakte.app beenden, `killall contactsd`; (2) alle leeren,
    verwaisten CardDAV-Quellen aus `~/Library/Application Support/AddressBook/Sources/` entfernen
    (Quellen mit 0 Karten und vorhandener `AddressBook-v22.abcddb`; echte lokale Kontakte-Quellen mit
    Karteninhalt nicht anfassen); (3) Account **neu und im Modus "Manuell"** anlegen, **nur mit dem
    Hostnamen** (`Fabio-Mac-Studio.local`), **ohne Port und ohne Pfad** — macOS macht dann die
    CardDAV-Autodiscovery über `/.well-known/carddav` selbst (wie beim iPhone) statt über einen fest
    eingetragenen Collection-Pfad. Danach sendete macOS sofort 28 `addressbook-multiget`-REPORTs und alle
    1535 Kontakte + 32 Gruppen kamen korrekt an (verifiziert in Kontakte.app auf dem Mac Studio).
  - **Für den iMac-Rollout:** Account **immer** im Modus "Manuell" mit nur dem Hostnamen anlegen, nie
    "Erweitert" mit explizitem Pfad — auch wenn beide Modi denselben Server ansprechen, verhält sich
    `contactsd` beim Auslösen des initialen Inhalts-Syncs unterschiedlich.
- Archivio enthält aktuell keine strukturierten Adressdaten, nur extrahierten Freitext (z. B. Mail-Signaturen) – die Extraktion daraus ist ein eigenständiges Teilproblem und bewusst auf später verschoben.
- pkg-Bündelung von Python + Radicale + Abhängigkeiten sollte sich eng am bestehenden Archivio-Build orientieren, um doppelte Lösungswege für dasselbe Problem zu vermeiden.
- SQLite-Eignung bei tatsächlicher Nutzung validieren (bei diesem Datenvolumen unkritisch, aber gleichzeitige Schreibzugriffe im Auge behalten).

## 10. Repo-Struktur

Flache Struktur analog zu Archivio (`/Users/fi/archivio`) statt einer `backend/frontend/packaging`-Aufteilung – gleiches, bewährtes Muster für Config-Loading, DB-Connection und spätere `.pkg`-Paketierung, keine doppelten Lösungswege für dasselbe Problem.

```
rubrica/
├── docs/
│   └── konzept.md          # dieses Dokument
├── config/
│   └── settings.py          # config.yaml laden/speichern (RUBRICA_DATA_DIR)
├── db/
│   ├── schema.sql
│   ├── connection.py
│   └── migrations.py
├── web/
│   ├── main.py               # FastAPI App-Factory
│   ├── contacts.py
│   ├── projects.py
│   ├── review.py
│   ├── templates/
│   └── static/
├── scripts/
│   ├── setup.sh
│   └── dev.sh
├── tests/
├── requirements.txt
├── config.yaml.example
├── CLAUDE.md
└── README.md
```

Radicale-Anbindung, launchd-Plists und `.pkg`-Build (Phase 2 ff.) werden zu gegebener Zeit ergänzt, sobald diese Phasen beginnen.

## 11. Umsetzungsstatus

| Phase | Status |
|---|---|
| 0 – Import + Dedup | Grundfunktion steht (vCard-Upload, Matching, Review-Queue) |
| 1 – Zentrale DB + Web-UI | Grundfunktion steht (Kontakte/Ordner-CRUD, Live-Suche) |
| 2 – Radicale/CardDAV | Sync-Engine steht (Push bei Kontakt-/Ordner-Änderung, echte htpasswd-Auth), end-to-end gegen echten Radicale-Server verifiziert |
| 3 – Export (Excel/PDF) | Noch nicht begonnen |
| 4 – Archivio-Integration | Zurückgestellt |

Umgesetzt und end-to-end im Browser verifiziert (2026-07-10):
- Kontakte bearbeiten/löschen inkl. mehrerer Telefonnummern/E-Mails/Adressen/URLs, Notizen, Zuordnung zu Ordnern. Bewusst keine manuelle Neuanlage in der App (siehe 5.1) — Anlage erfolgt in Kontakte.app + Import
- Ordner anlegen/löschen, Live-Suche/Filter (Name, Firma, Ordner, Kategorie) per htmx (nutzerseitig "Ordner", intern weiterhin Tabelle `projekte`, siehe 5.4)
- vCard-Import (mehrere Dateien gleichzeitig, Einzel- wie Batch-Export, inkl. Apple-Gruppen-Erkennung über `X-ADDRESSBOOKSERVER-KIND`/`MEMBER`), Feldabdeckung inkl. Postadresse/Homepage/Notizen an echter Nutzung im bestehenden Adressbuch verifiziert (siehe Abschnitt 4)
- Dedup-Matching (E-Mail exakt → Telefonnummer normalisiert → Vor-/Nachname) erzeugt `vorschlaege`, nie direkte Änderung
- Review-Queue: Bestätigen mergt (ergänzt Telefonnummern/E-Mails/Adressen/URLs, hängt Notizen an, überschreibt nur leere Felder), Ablehnen verwirft — bestehende Kontakte werden nie automatisch verändert
- Batch-Import mit 60 synthetischen Kontakten performant und korrekt (Test); 20 pytest-Tests (Schema, Foreign-Keys, Import/Matching/Merge, Radicale-Sync) grün
- Radicale-Spike: Apple-Gruppen-Anzeige auf iPhone erfolgreich bestätigt (siehe Abschnitt 9), Kernrisiko von Phase 2 damit ausgeräumt
- **Sync-Engine** (`sync/radicale.py`): Kontakt- und Ordner-vCards werden bei jeder relevanten Änderung
  (Kontakt bearbeiten/löschen, Ordner anlegen/löschen, Vorschlag bestätigen) automatisch per CardDAV `PUT`/
  `DELETE` nach Radicale geschrieben, inkl. automatischem Anlegen der Adressbuch-Collection (`MKCOL`) beim
  ersten Zugriff. End-to-end mit echtem Radicale-Server (htpasswd/bcrypt-Auth, HTTPS) verifiziert: Kontakt
  anlegen+Ordner zuordnen → beide vCards korrekt in Radicale; Kontakt löschen → vCard entfernt, Ordner-
  Gruppe automatisch ohne den Kontakt neu geschrieben. Konfiguration über `radicale.*` in `config.yaml`,
  standardmässig deaktiviert.
- **Umbenennung (2026-07-10):** "Projekte" heisst nutzerseitig jetzt durchgehend "Ordner" (Navigation, Formulare,
  URLs `/ordner*`) — Datenbank-Tabellen (`projekte`, `kontakte_projekte`) und interne IDs (`projekt-{id}` im
  Radicale-UID-Schema) bleiben bewusst unverändert, um kein Migrationsrisiko ohne Nutzen einzugehen.
- **Echter Datenimport (2026-07-10):** `scripts/import_from_contacts_app.py` importiert alle Kontakte + Gruppen
  direkt per AppleScript aus Kontakte.app (statt manuellem vCard-Export), verifiziert am tatsächlichen
  Adressbuch: 1503 von 1504 Kontakten erfolgreich übernommen (1 mit defekter Legacy-Quoted-Printable-Kodierung
  übersprungen), 32 Ordner mit korrekter Mitgliederzuordnung — Zahlen decken sich exakt mit den echten
  Kontakte.app-Gruppen. Datenschutz-Vorkehrung: keine Zwischendateien, keine vollständigen Datensätze im
  Skript-Output, nur zusammenfassende Zahlen.
  **Bug gefunden + behoben:** Apple's gruppierte vCard-Properties (`item2.X-ABADR:...`, Punkt vor dem
  Property-Namen für benutzerdefinierte Adress-Labels) wurden von der Zeilenfaltungs-Reparatur des Skripts
  fälschlich als verwaiste Fortsetzungszeile erkannt und an die vorherige Adresse angehängt — betraf
  vereinzelt Adressfelder. Regex korrigiert (erlaubt jetzt Punkte im Property-Namen), DB komplett neu
  importiert. Zusätzlich in `sync/radicale.py` eine RFC-6350-Zeilenfaltung (`_fold`) ergänzt, da einzelne
  besonders lange vCard-Zeilen von Radicale mit 400 Bad Request abgelehnt wurden. Nach beiden Fixes: alle
  1503 Kontakte + 32 Ordner fehlerfrei nach Radicale synchronisiert (1535 Einträge per CardDAV verifiziert).
- **Test-`.pkg` mit launchd + Zertifikat (2026-07-10):** `scripts/build-pkg.sh` baut `Rubrica Server.app`
  (kein eingebettetes Python — venv wird beim Erststart mit System-Python aufgebaut, analog Archivios
  Fallback-Pfad) und ein `.pkg`, das zwei launchd-Dienste einrichtet (`ch.strut.rubrica.server`,
  `ch.strut.rubrica.radicale`), beim Erststart automatisch ein selbstsigniertes Zertifikat sowie ein
  zufälliges CardDAV-Passwort erzeugt (`htpasswd`/bcrypt) und die Zugangsdaten per Dialog + Textdatei anzeigt.
  Lokal auf dem Mac Studio installiert und verifiziert (beide Dienste laufen, Web-UI erreichbar, Sync gegen
  echten Radicale-Server bestätigt). Zwei Stolpersteine dabei gefunden und behoben:
  - macOS' PackageKit "relocated" die Installation in den lokalen Build-Ordner (`dist/…`) statt nach
    `/Applications`, weil dort zum Installationszeitpunkt bereits ein Bundle mit derselben
    `CFBundleIdentifier` lag (Launch-Services-Erkennung) — `build-pkg.sh` entfernt den Build-Ordner jetzt
    nach dem Packen und hebt dessen Launch-Services-Registrierung explizit auf.
  - Beide launchd-Dienste teilen sich ein venv und starten gleichzeitig (`RunAtLoad`) — ohne Sperre
    entstand eine Race Condition beim venv-Aufbau. Behoben mit einer einfachen `mkdir`-basierten Lockdatei
    in der gemeinsamen Bootstrap-Logik.
- **CardDAV-Zertifikat + macOS-Sync vollständig gelöst (2026-07-12):** siehe Abschnitt 9 für die Details
  (Ursache: nicht Apple-konformes selbstsigniertes Zertifikat + macOS-Client-Zustand/Setup-Modus). Neue
  `scripts/generate-cert.sh` (lokale CA + konformes Leaf) ist in `build-pkg.sh` eingebaut; der Postinstall
  erzeugt das Zertifikat und markiert die CA automatisch systemweit als vertrauenswürdig (`security
  add-trusted-cert` als root, kein manueller Dialog nötig). `.pkg` mit diesem Fix neu gebaut
  (`dist/rubrica-server-0.1.0-test.pkg`) und Payload/Postinstall verifiziert (`generate-cert.sh` enthalten,
  `add-trusted-cert`-Aufruf vorhanden). End-to-End auf dem Mac Studio bestätigt: Account im Modus
  "Manuell" (nur Hostname) synchronisiert alle 1535 Karten + 32 Gruppen korrekt in Kontakte.app.
  `scripts/fix-macos-trust.sh` steht für bestehende Installationen ohne neuen Postinstall bereit.
- **Eingebettetes Python im `.pkg` (2026-07-12):** `build-pkg.sh` lädt jetzt analog zu Archivios
  `build_server_app.sh` universelles Python 3.13 via `python-build-standalone` (arm64 **und** x86_64,
  Cache über MD5-Hash von `requirements.txt`), installiert alle Abhängigkeiten hinein und kopiert beide
  Umgebungen nach `Contents/Frameworks/rubrica-python-{arch}/` ins App-Bundle (Ad-hoc-Codesignierung der
  `.so`/`.dylib`/Binaries für Gatekeeper). Beide Launcher (`Rubrica Server`, `Rubrica Radicale`) bevorzugen
  das eingebettete Python der laufenden Architektur (`uname -m`) und fallen nur, falls für diese Architektur
  kein eingebettetes Python mitgeliefert wurde, auf den alten System-Python+venv-Weg zurück
  (`bootstrap_venv.sh`, unverändert als Fallback erhalten). Grund: **kein** Abhängigkeit mehr von der
  jeweils auf iMac/Mac Studio installierten Python-Version — iMac und Mac Studio können unterschiedliche
  oder gar keine Python-Installation haben, ohne dass es zu Versions-/Paketkonflikten kommt.
  `.pkg`-Größe dadurch von 46 KB auf ~92 MB gestiegen (zwei komplette Python-Laufzeiten inkl. FastAPI/
  Uvicorn/Radicale/bcrypt/vobject) — bewusst in Kauf genommen für Robustheit, deutlich kleiner als Archivios
  ~290 MB (kein PyMuPDF/PyObjC). Lokal auf dem Mac Studio installiert und verifiziert: beide Prozesse laufen
  nachweislich unter `Contents/Frameworks/rubrica-python-arm64/bin/python3` (nicht mehr unter dem alten
  venv), Web-UI (200) und CardDAV (207) funktionieren, alle 1503 Kontakte/32 Ordner/1535 Radicale-Karten
  unverändert erhalten. Altes, jetzt ungenutztes venv unter `~/Library/Application Support/Rubrica/.venv`
  entfernt.
  - **Stolperstein:** `launchctl bootstrap` im Postinstall-Skript schlug fehl, als das `.pkg` über
    `osascript … with administrator privileges` (GUI-Passwortdialog statt Terminal-`sudo`) installiert
    wurde — die LaunchAgents wurden zwar als Plist geschrieben, aber nicht in die GUI-Sitzung eingehängt.
    Workaround: einmalig manuell `launchctl bootstrap gui/<uid> <plist>` je Dienst. Für den iMac-Rollout
    testen, ob Installation über Doppelklick/Finder (statt osascript-Fernsteuerung) davon unberührt ist.

Bekannte Einschränkung: Entwicklungsumgebung läuft unter Python 3.9 (Systemversion) statt der ursprünglich in Abschnitt 6 vermuteten 3.12 — FastAPI-Routenparameter deshalb mit `typing.Optional[int]` statt `int | None` (siehe `CLAUDE.md`). Dies betrifft nur die lokale Entwicklungsumgebung; das produktive `.pkg` bringt sein eigenes Python 3.13 mit und ist davon unabhängig.

Nächste sinnvolle Schritte: `.pkg` auf dem echten iMac installieren (Account beim Einrichten im Modus
"Manuell" mit nur dem Hostnamen anlegen, siehe Abschnitt 9), danach Phase 3 (Excel/PDF-Export).
