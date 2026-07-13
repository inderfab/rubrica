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
- **Direktes Neuanlegen von Kontakten über die Web-UI (`/kontakte/neu`, umgesetzt 2026-07-12).**
  *Revidiert die ursprüngliche Entscheidung „bewusst keine Neuanlage".* Grund: Das Kernproblem des Büros
  ist, dass Kontakte **gar nicht erst erfasst** werden (Wissen bleibt bei Einzelpersonen). „In Kontakte.app
  anlegen → exportieren → importieren" ist genau die Reibung, die das verhindert. Ein Web-Formular zum
  Neuanlegen braucht **keinen** bidirektionalen Sync (Rubrica bleibt Single Source of Truth, pusht einseitig
  zu Apple) und ist daher voll mit dem Architekturprinzip vereinbar. Das Formular ist bewusst minimal und
  mobiltauglich. **Reibungssenker: E-Mail-Signatur einfügen** → `importer/signatur.py` parst sie und füllt
  die Felder vor (danach editierbar). Kontakte werden **direkt angelegt** (kein Freigabe-Gate — Reibung
  würde die Erfassung verhindern), nachträglich korrigierbar; Duplikat-Bereinigung ist Admin-Aufgabe über
  die Review-Queue (Ausbau geplant). Der bisherige Weg (Import aus Kontakte.app, 5.6) bleibt zusätzlich
  bestehen.
- **Feld „Funktion"** (Fachrichtung: Architekt, Bauingenieur, Geologe, div. Planer …) pro Kontakt, damit der
  Chef nach Ansprechpartner-Rolle filtern/exportieren kann. Auswahlliste + Freitext (nicht erzwungen).
  Technisch im bestehenden Feld `kategorie` gespeichert (nur UI-Label „Funktion"), keine DB-Migration.
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
- **Import bleibt *ein* Weg der Erfassung (neben der direkten Web-Neuanlage, siehe 5.1), aber der einzige aus Kontakte.app zurück.** Grund: eine echte bidirektionale CardDAV-Synchronisation (Kontakte.app ↔ App) würde das Kernprinzip "nie automatisches Überschreiben" aushebeln, weil Änderungen aus Kontakte.app dann ungeprüft durchschlagen würden. Radicale bleibt nur Ausgaberichtung (App → Apple Kontakte für Klickwahl); die Rückrichtung aus Kontakte.app bleibt bewusst Export → Import → Review-Queue. (Direktes Neuanlegen in der Web-UI umgeht Kontakte.app ganz und ist davon unberührt.)
- Import-Parser mappt vCard-Felder auf das Datenmodell: Name, Firma, Rolle, Telefonnummern, E-Mails, Postadressen (ADR), Homepage/URLs, Notizen (NOTE).
- Da mehrere, teils überlappende Mitarbeiter-Kopien existieren: alle Exporte importieren und dieselbe Review-Queue-Logik (siehe `VORSCHLAEGE`-Tabelle) für die Dedup-/Zusammenführung nutzen – keine zweite Logik nötig, auch nicht für die spätere Archivio-Integration. Matching-Reihenfolge: exakte E-Mail → normalisierte Telefonnummer → exakter Vor-/Nachname.
- Bestehende lokale Gruppen aus dem Import können optional als erste Ordner übernommen werden (Apple-Gruppen-vCards mit `X-ADDRESSBOOKSERVER-KIND`/`MEMBER`, in der Praxis am bestehenden Adressbuch verifiziert: ~32 Gruppen bei 1538 Kontakten).

### 5.7 Export
- **Umgesetzt (Phase 3, 2026-07-12):** `/export` — Nutzer wählt einen Ordner (oder "Alle Kontakte") und
  ein oder mehrere Formate (PDF, CSV, vCard), Rubrica liefert alle gewählten Dateien gebündelt als ein
  einziges ZIP-Archiv (`Ordnername_JJJJ-MM-TT.zip`) zum Download. Erzeugung in `export/generator.py`:
  - **PDF:** formatierte Liste (reportlab), pro Kontakt ein zusammenhängender Block (Name, Firma/Rolle,
    Telefon/E-Mail/Adresse/Web, Notizen), Titel + Datum + Anzahl Kontakte im Kopf.
  - **CSV:** Excel-kompatibel (Semikolon-getrennt, UTF-8 mit BOM für korrekte Umlaut-Darstellung in Excel).
  - **vCard:** eine `.vcf`-Datei mit allen Kontakten des Ordners (Mehrfach-vCard, direkt per Doppelklick in
    Kontakte.app importierbar) — nutzt dieselbe `kontakt_zu_vcard()`-Funktion wie der CardDAV-Sync
    (`sync/radicale.py`), keine doppelte Formatierungslogik.
  - Neue Abhängigkeit `reportlab==5.0.0` in `requirements.txt`.

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
| 3 ✅ | Export-Funktionen (PDF/CSV/vCard, pro Ordner, siehe Abschnitt 5.7) |
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
- **Produktiv-Rollout auf dem iMac erfolgreich abgeschlossen (2026-07-12):** `.pkg` auf dem iMac (Intel,
  x86_64) installiert und verifiziert — eingebettetes Python lief dort korrekt nativ (`rubrica-python-x86_64`,
  Python 3.13.14), bestätigt die Architektur-Unabhängigkeit des neuen Pakets. Mehrere Probleme dabei
  gefunden und gelöst:
  - **Port-Konflikt mit Archivio:** Archivio belegt auf dem iMac bereits Port 8000 (Rubricas alter
    Standard-Port) — `[Errno 48] address already in use`. Rubricas Web-Server-Port fest auf **8001** verlegt
    (`config.yaml.example`, `scripts/dev.sh`, `scripts/build-pkg.sh`-Launcher), um Konflikte auf gemeinsam
    genutzten Maschinen generell zu vermeiden.
  - **Datenmigration Mac Studio → iMac:** Da jede `.pkg`-Installation eine eigene, leere Datenbank anlegt,
    mussten die 1503 Kontakte/32 Ordner separat übertragen werden (kein SSH-Zugriff auf den iMac gewünscht).
    Neues `scripts/restore-data-archive.sh`: spielt ein Archiv (`rubrica.db` + Radicale-vCards) auf der
    Zielinstallation ein, ohne Zertifikat/Passwort/Config anzutasten (bleiben pro Maschine eigenständig).
  - **Altes, nicht-konformes Zertifikat auf dem iMac:** Von einem noch früheren Installationsversuch (vor
    dem CA-Fix) lag dort schon ein `cert.pem` — der Postinstall überspringt die Neuerzeugung, wenn die
    Datei schon existiert. Musste einmalig manuell nachgeholt werden (altes Zertifikat entfernen,
    `generate-cert.sh` erneut ausführen, neue CA per `security add-trusted-cert` vertrauen — sowohl auf dem
    iMac selbst als auch auf dem Mac Studio, da jede Installation ihre **eigene** CA erzeugt und Clients
    diese jeweils einzeln vertrauen müssen).
  - **Kritischer Bug in `restore-data-archive.sh` gefunden (behoben, siehe Commit `3a4629b`):** Das Skript
    legte den Collection-Ordner per rohem `mkdir` an, statt Radicales eigene MKCOL-Verarbeitung zu nutzen.
    Dadurch fehlte `.Radicale.props` (Tag `VADDRESSBOOK`) — PROPFIND/Login/Discovery funktionierten
    einwandfrei (207 OK), aber macOS Kontakte.app erkannte den Ordner mangels korrektem
    `resourcetype: CR:addressbook` nicht als synchronisierbares Adressbuch und sendete nie einen `REPORT`.
    Exaktes Symptom wie das ursprüngliche TLS-Problem aus Abschnitt 9 ("Verbindung klappt, Kontakte bleiben
    leer"), diesmal aber bei sauberem Zertifikat — wichtige Erkenntnis: **dasselbe äußere Symptom kann
    mehrere unabhängige Ursachen haben** (TLS-Vertrauen UND Collection-Metadaten UND Cache-Timeout, siehe
    unten, traten in dieser Session alle drei nacheinander auf). Fix: `restore-data-archive.sh` schreibt
    `.Radicale.props` jetzt automatisch nach, falls sie fehlt.
  - **Cache-Kaltstart-Timeout:** Nach dem Löschen von `.Radicale.cache` (Teil der Migration) brauchte
    Radicale beim ersten Zugriff auf die 1535-Karten-Collection auf dem iMac **138 bzw. 55 Sekunden**, um
    den Cache neu aufzubauen (`PROPFIND ... depth 1` im Log) — deutlich über dem Timeout, den macOS'
    Kontakte-Sync-Daemon offenbar zulässt, wodurch der Client vor Erhalt der (verspäteten) Antwort bereits
    aufgegeben hatte. Nach einmaligem "Aufwärmen" des Caches lief ein erneuter Versuch (Kontakte.app
    beenden, `contactsd` zurücksetzen, neu öffnen) in Sekunden durch. Merke für künftige Migrationen: nach
    dem Löschen von `.Radicale.cache` einmal die Collection warm anfragen (z. B. per `curl PROPFIND`),
    bevor man macOS synchronisieren lässt.
  - **Ergebnis:** Kontakte.app auf dem Mac Studio synchronisiert erfolgreich gegen den Rubrica-Server auf
    dem iMac (`Windows.local`) — alle 1503 Kontakte angekommen, verifiziert über den lokalen
    AddressBook-Sources-Cache (`~/Library/Application Support/AddressBook/Sources/*/Metadata/*.abcdp`).
    Der lokale Testserver auf dem Mac Studio wurde gestoppt (nicht deinstalliert), um Doppelbetrieb mit
    divergierenden Datenständen zu vermeiden — der iMac ist jetzt die einzige aktive Instanz.
- **Phase 3: Export (2026-07-12):** siehe Abschnitt 5.7 für die Details. Neues Modul `export/generator.py`
  (PDF/CSV/vCard-Erzeugung, 5 Tests in `tests/test_export.py`) + `web/export.py` (Route `/export`,
  Formular- und ZIP-Logik) + Template `web/templates/export.html` + Nav-Link in `base.html`. Lokal end-to-end
  gegen echte Daten getestet (Ordner mit 10 echten Kontakten exportiert, alle drei Formate im ZIP korrekt:
  CSV mit korrekten Umlauten, 10 vCards, gültiges PDF). Alle 27 Tests (bestehend + neu) grün.
  **Hinweis:** Das produktive `.pkg` auf dem iMac/Mac Studio wurde noch nicht mit der neuen
  `reportlab`-Abhängigkeit neu gebaut/installiert — vor Nutzung des Exports in Produktion `.pkg` neu bauen
  und ausrollen (`scripts/build-pkg.sh`, danach Installation + `.venv`/eingebettetes Python aktualisieren).

Bekannte Einschränkung: Entwicklungsumgebung läuft unter Python 3.9 (Systemversion) statt der ursprünglich in Abschnitt 6 vermuteten 3.12 — FastAPI-Routenparameter deshalb mit `typing.Optional[int]` statt `int | None` (siehe `CLAUDE.md`). Dies betrifft nur die lokale Entwicklungsumgebung; das produktive `.pkg` bringt sein eigenes Python 3.13 mit und ist davon unabhängig.

- **Erfassung / Kontakt-Neuanlage (2026-07-12):** siehe Abschnitt 5.1. `importer/signatur.py` (Signatur →
  Kontaktfelder, 10 Tests), `web/contacts.py` (Routen `/kontakte/neu`, `/kontakte/signatur-parsen`), Templates
  `contact_new.html` + Fragment `_kontakt_felder.html`, Feld „Funktion" in Neuanlage/Bearbeiten/Liste/Filter/
  Export. 3 Web-Smoke-Tests, alle 40 Tests grün. Lokal end-to-end verifiziert (Anlegen inkl.
  Signatur-Vorbefüllung, Funktion in Liste, danach sauber gelöscht — Produktiv-DB unverändert).

**Strategische Richtung (mit Nutzer abgestimmt, 2026-07-12):** Kernproblem ist *Wissenszentralisierung* —
Kontakte werden nicht erfasst, darum kennt z. B. die Geschäftsleitung Ansprechpartner nicht. Zwei Hebel:
(1) reibungslose *aktive* Erfassung (Web-Formular + Signatur-Einfügen, umgesetzt) und (2) *passive* Erfassung
via Archivio (E-Mail-Signaturen → **gefilterte Vorschläge** in die Review-Queue, `vorschlaege.quelle='archivio'`
existiert bereits; hohe Präzision statt Vollständigkeit, um Explosion der Kontaktzahl zu vermeiden — nächster
grösserer Schritt). Bewusst *nicht* jetzt: Notion-Pendenzen-Kopplung (eher umständlich als hilfreich; höchstens
später dünne Einbahn-Brücke Kontakte→Notion, wenn Schmerz bewiesen) und schwere Rechte-Bürokratie (Freigabe-Gate
vor Erfassung würde die Adoption abwürgen). Später: sicherer Remote-Zugriff für On-Site-Erfassung.

- **`.pkg`-Rebuild + Testinstall auf dem Mac Studio (2026-07-12):** Neues `.pkg` mit `reportlab` gebaut und
  probeweise installiert (Dienste danach bewusst wieder gestoppt — der iMac bleibt die einzige aktive
  Instanz). Dabei **Bug gefunden + behoben:** `scripts/build-pkg.sh` kopierte das `export/`-Verzeichnis nie
  ins App-Bundle (`Contents/Resources`), obwohl `web/export.py` es importiert — Symptom: Server-Dienst
  startete nicht (`ModuleNotFoundError: No module named 'export'`, Exit 1). Nach Fix neu gebaut und
  vollständig end-to-end gegen die echte `.pkg`-Installation verifiziert: Export (PDF/CSV/vCard), Signatur-
  Parsen und Kontakt-Neuanlage funktionieren alle korrekt mit dem eingebetteten Python; Produktions-DB
  danach unverändert (Testkontakt angelegt und wieder gelöscht, 1503→1503).
- **Archivio-Anbindung, erste Stufe (2026-07-12):** Neues Modul `archivio_bridge/anbindung.py` (bewusst
  nicht `archivio` genannt, um Verwechslung mit dem Referenzprojekt `/Users/fi/archivio` zu vermeiden) liest
  read-only aus Archivios SQLite-DB (Tabellen `documents`/`document_content`/`mails`, bereits text-
  extrahierte E-Mails) und erzeugt daraus Kandidaten für die Review-Queue. Strenger Vorfilter wie in der
  strategischen Richtung festgelegt: nur Absender mit ≥ `archivio.min_mails` E-Mails (echte Korrespondenz),
  nur wenn die per `importer/signatur.py` geparste Signatur **sowohl Telefonnummer als auch Firma** enthält,
  bereits vorhandene E-Mail-Adressen werden übersprungen. Schreibt selbst nichts — neue Route
  `/review/archivio-vorschau` (GET, reine Vorschau ohne DB-Schreibzugriff) + `/review/archivio-uebernehmen`
  (POST, erzeugt `vorschlaege` mit `quelle='archivio'`, dublettensicher gegenüber bereits offenen Archivio-
  Vorschlägen). Konfiguration über `archivio.db_path`/`archivio.min_mails` in `config.yaml` (leer = aus).
  9 Tests (5 Modul-Ebene mit synthetischer Archivio-Test-DB, 4 Web-Ebene inkl. Dubletten-Schutz).
  **Gegen echte Daten verifiziert** (Projekt `215_Flurhofstrasse`, 156 bereits gescannte E-Mails, 17
  Absender, 9 mit ≥2 Mails): **2 valide Kandidaten** gefunden, beide mit Name/Firma/Telefon/Mail, aus
  echter mehrfacher Korrespondenz (5 bzw. 26 Mails) — Verifikation bewusst nur mit aggregierten
  Kennzahlen (Feld vorhanden ja/nein, Längen, Anzahl), nie mit echtem Klartext im Chat/Terminal-Output.
  Kleine Fundgrösse liegt am Datenbestand: bisher ist nur ein einziges Projekt-Postfach in Archivio
  gescannt (`mail_scan_config.active=1` bei nur 3 von 59 Ordnern) — mehr Ertrag braucht mehr gescannte
  Postfächer in Archivio selbst (liegt ausserhalb von Rubrica).

**Strategische Richtung (mit Nutzer abgestimmt, 2026-07-12):** Kernproblem ist *Wissenszentralisierung* —
Kontakte werden nicht erfasst, darum kennt z. B. die Geschäftsleitung Ansprechpartner nicht. Zwei Hebel:
(1) reibungslose *aktive* Erfassung (Web-Formular + Signatur-Einfügen, umgesetzt) und (2) *passive* Erfassung
via Archivio (E-Mail-Signaturen → **gefilterte Vorschläge** in die Review-Queue, umgesetzt siehe oben;
hohe Präzision statt Vollständigkeit, um Explosion der Kontaktzahl zu vermeiden). Bewusst *nicht* jetzt:
Notion-Pendenzen-Kopplung (eher umständlich als hilfreich; höchstens später dünne Einbahn-Brücke
Kontakte→Notion, wenn Schmerz bewiesen) und schwere Rechte-Bürokratie (Freigabe-Gate vor Erfassung würde
die Adoption abwürgen). Später: sicherer Remote-Zugriff für On-Site-Erfassung.

- **Menubar-App ersetzt zwei separate launchd-Dienste (2026-07-12):** Bisher liefen Web-Server und Radicale
  als zwei unabhaengige launchd-Dienste (`ch.strut.rubrica.server`, `ch.strut.rubrica.radicale`) ohne jede
  sichtbare Statusanzeige. Problem: Kein Weg zu sehen, ob Rubrica laeuft, und ein einfaches Beenden des
  Prozesses haette wegen `KeepAlive=true` sofort zu einem Neustart durch launchd gefuehrt — ein
  Drüber-Installieren waere daher nicht sauber gewesen. Neues `menubar/app.py` (rumps, analog zu Archivios
  `menubar/server_app.py`): **ein einziger** launchd-Job startet diese Menubar-App, die Web-Server und
  Radicale selbst als Kindprozesse startet, ueberwacht (Neustart bei Absturz, ersetzt die launchd-KeepAlive-
  Ueberwachung, die jetzt nur noch den Wrapper selbst betrifft) und sauber beendet. Menu zeigt
  Live-Status (🟢/🔴) fuer beide Dienste, "Rubrica öffnen", "Datenordner öffnen", "Beenden" (stoppt beide
  Kindprozesse, entlaedt den eigenen launchd-Job via `launchctl bootout`, beendet sich selbst — kein
  ungewollter Neustart durch KeepAlive). Neue Abhaengigkeit `rumps==0.4.0` (+ pyobjc automatisch via pip),
  Groessenzuwachs im `.pkg` nur ~5 MB. `scripts/build-pkg.sh` entsprechend umgebaut: nur noch ein Launcher-
  Binary ("Rubrica Server", jetzt Wrapper statt direktem `uvicorn`-Exec), Postinstall installiert nur noch
  einen LaunchAgent und raeumt den alten `ch.strut.rubrica.radicale`-Agent von frueheren Installationen auf
  (Migration). End-to-end auf dem Mac Studio installiert und verifiziert: Status-Icon sichtbar, beide
  Kindprozesse laufen (Web-UI 200, Radicale-TLS OK), "Beenden" funktioniert sauber.
- **Kontaktliste: Ordner-Seitenleiste mit Drag & Drop (2026-07-12):** `/kontakte` umgebaut auf ein
  zweispaltiges Layout (Ordner-Sidebar links mit Kontakt-Anzahl je Ordner, Kontaktliste rechts) — angelehnt
  an Kontakte.app, wie vom Nutzer gewuenscht, weil das Zuordnen zu Ordnern vorher nicht auffindbar war
  (nur ueber den Bearbeiten-Link, der optisch nicht auffiel). Kontakt-Zeilen sind per HTML5 Drag&Drop auf
  einen Ordner in der Sidebar ziehbar (Ziehgriff „⠿"); Ablegen ruft eine neue Route
  `POST /kontakte/{id}/ordner/{ordner_id}/hinzufuegen` auf, die den Ordner **ergaenzt** statt die gesamte
  Zuordnung zu ersetzen (neue `db.queries.add_kontakt_projekt`, additive Variante zu `set_kontakt_projekte`).
  Volle Kontrolle (inkl. Entfernen aus Ordnern) bleibt zusaetzlich ueber das bestehende Bearbeiten-Formular
  moeglich. 4 neue Tests, gegen echte Produktionsdaten auf dem Mac Studio end-to-end verifiziert (Testkontakt
  angelegt, per simuliertem Drop einem echten Ordner zugeordnet, Tag erschien korrekt in der Liste, danach
  sauber geloescht).

- **Bugfix Drag&Drop blockierte Bearbeiten-Klick (2026-07-12):** Nutzer-Feedback nach dem ersten Live-Test
  auf dem iMac: Ordner-Sidebar und Drag&Drop funktionierten, aber der Klick auf den Kontaktnamen (Link zu
  `/kontakte/{id}/bearbeiten`) reagierte nicht zuverlässig. Ursache: `draggable="true"` stand auf der ganzen
  `<tr>` — jede minimale Mausbewegung beim Klicken wurde vom Browser als Drag-Start statt als Klick
  interpretiert. Fix: `draggable` nur noch auf dem Ziehgriff-`<td>` ("⠿"), der Rest der Zeile (inkl.
  Name-Link) ist normal klickbar. Live auf dem Mac Studio verifiziert.
- **Einstellungsseite (2026-07-12):** Nutzer-Feedback: `archivio.db_path` liess sich nicht setzen, weil die
  `archivio:`-Sektion in bestehenden `config.yaml`-Dateien (vor dieser Funktion installiert) schlicht fehlte
  und Hand-Editieren von YAML fehleranfaellig ist. Neue Seite `/einstellungen` (`web/settings.py` +
  `templates/settings.html`, Nav-Link): Formular für Archivio-Datenbankpfad + Mindestanzahl E-Mails,
  schreibt über die bestehende `config.settings.save()` (deep-merge, legt fehlende Sektionen automatisch an).
  3 Tests. Live gegen die echte Mac-Studio-Config verifiziert: bestehende `config.yaml` ohne `archivio:`-
  Sektion wurde korrekt ergänzt, andere Werte (Radicale-Zugangsdaten etc.) blieben unangetastet; danach
  `archivio.db_path` auf den echten lokalen Pfad (`/Users/fi/archivio/archivio.db`) gesetzt — Archivio-Vorschau
  darüber erfolgreich aufgerufen (0 Kandidaten, weil die zuvor gefundenen 2 Personen als Kontakt bereits
  vorhanden sind — Dublettenschutz korrekt gegen den vollen 1503-Kontakte-Bestand verifiziert).

- **Bearbeiten-Flyover + Drag-Ziehbild + Archivio-Qualitaet (2026-07-12, Nutzer-Feedback nach Live-Test):**
  - **Bearbeiten war nicht auffindbar:** Name-Klick funktionierte fuer den Nutzer trotz Drag&Drop-Fix nicht
    zuverlaessig. Neu: expliziter **„Bearbeiten"-Button links vom „Löschen"-Button**, oeffnet den Kontakt als
    **Flyover** (Modal-Overlay) statt Seitenwechsel — per htmx-Fragment (`kontakt_bearbeiten_modal.html`,
    gemeinsames Formular-Include `_kontakt_bearbeiten_form.html`, geteilt mit der Vollseite
    `contact_form.html`, keine doppelte Logik). Name in der Liste ist wieder reiner Text (kein Link mehr) -
    Bearbeiten geht ausschliesslich ueber den Button.
  - **Ziehbild beim Drag&Drop:** Der Ziehgriff „⠿" allein zeigte waehrend des Ziehens nicht, welcher Kontakt
    gerade bewegt wird. Custom Drag-Image (`DataTransfer.setDragImage`) zeigt jetzt „⠿ Vorname Nachname"
    waehrend des Ziehens.
  - **Archivio-Kandidatenqualitaet grundlegend ueberarbeitet** nach konkretem Nutzer-Feedback (Funktions-
    zeile als Name, fehlende E-Mail, Newsletter-Text als Firma, unplausible Telefonnummer, bereits
    bestehende Kontakte tauchten erneut auf):
    - **Ursachenklaerung (Nutzerfrage beantwortet):** Ja, Archivio hat einen Signatur-Entferner. In
      `archivio/scanner/mail_scanner.py` schneidet `_strip_signature` bei IMAP-gescannten Mails ALLES nach
      einer Grussformel ("Freundliche Grüsse" etc.) ab, bevor der Text ueberhaupt in Archivios DB landet —
      der Rohtext wird nirgends aufbewahrt, das ist fuer IMAP-Mails unwiederbringlich (nur bei
      `.eml`-Dateien im Dateisystem-Scan bleibt die Signatur intakt). Erklaert fehlende E-Mails/Namen direkt
      an der Quelle, nicht in Rubrica behebbar.
    - **`importer/signatur.py` gehaertet:** Regex-Bug behoben (`\bdipl\.\b` matcht nie, wenn ein Punkt von
      einem Leerzeichen gefolgt wird — beide Nicht-Wortzeichen, keine Wortgrenze); Namens-Erkennung lehnt
      jetzt Zeilen ab, die wie eine Funktion/Titel aussehen (`_ROLLE_KENNUNG`-Ueberschneidung); Firma auf
      max. 80 Zeichen begrenzt (verhindert Newsletter-Absaetze als "Firma"); neue
      `_ist_plausible_telefonnummer()` verwirft Zahlenfolgen mit ungueltiger Schweizer Vorwahl (zweite
      Ziffer nach der Landes-/Trunk-Null darf nie 0 oder 1 sein — verwirft z. B. "011 8544 000").
    - **`archivio_bridge/anbindung.py` strenger gefasst:** verlangt jetzt ALLE VIER Felder vollstaendig
      (Vor- UND Nachname, Firma, mind. 1 Telefonnummer, mind. 1 E-Mail) statt nur Telefon+Firma; probiert
      bis zu 5 Mails je Absender (nicht nur die neueste), falls eine durch Archivios Signatur-Kappung
      unvollstaendig ist; Dublettenpruefung jetzt zusaetzlich per Name und Telefonnummer (nicht nur E-Mail).
    - 9 neue/aktualisierte Tests fuer `archivio_bridge` (16 fuer `signatur.py` insgesamt), alle synthetisch
      nachgebaut aus den konkret gemeldeten Faellen. Live gegen den echten Archivio-Bestand erneut verifiziert:
      0 Kandidaten (vorher 2, beide waren unvollstaendig — jetzt korrekt durch den strengeren Filter
      ausgeschlossen).

- **Archivio-Vorschau: einzeln übernehmen/ablehnen (2026-07-12):** Nutzer-Feedback — bisher gab es nur
  "alle übernehmen". Neue Routen `POST /review/archivio-uebernehmen-einzeln` und
  `POST /review/archivio-ablehnen` (je per E-Mail-Adresse identifiziert, die durch die strenge
  Vollstaendigkeitspruefung immer vorhanden ist). Ablehnen legt einen Vorschlag mit Status `abgelehnt` an
  (kein neuer Mechanismus noetig — nutzt die bestehende `vorschlaege`-Tabelle); `archivio_bridge`s
  Dublettenpruefung wurde erweitert, sodass **jeder** bereits per Archivio-Vorschau entschiedene Kandidat
  (uebernommen ODER abgelehnt) nicht wieder auftaucht, nicht nur bereits bestehende Kontakte. "Alle
  übernehmen" bleibt zusaetzlich als Bulk-Option bestehen. 6 neue Tests.
- **Ordner: Bearbeiten-Button (2026-07-12):** `/ordner` hatte keine Umbenennen-Funktion. Neue Route
  `POST /ordner/{id}/bearbeiten` (`db.queries.rename_projekt`) + inline editierbarer Name in der Liste
  (JS-Toggle zwischen Anzeige und Eingabefeld, kein Flyover noetig fuer ein einzelnes Feld). 3 Tests.
- **Ordner-Checkliste im Kontakt-Formular als vertikale Liste:** war ein zeilenweise umbrechendes Grid,
  bei 30+ Ordnern unuebersichtlich (Nutzer-Feedback, Screenshot). Jetzt eine scrollbare, alphabetisch
  sortierte vertikale Liste (`.ordner-checkliste`, max-height 220px) — in `_kontakt_bearbeiten_form.html`
  und `_kontakt_felder.html` (Neu-Anlegen) gleichermassen.

**Offener Punkt (zurueckgestellt, 2026-07-12): Archivio-Mailscanner soll Signatur separat speichern.**
Wurde ausfuehrlich mit dem Nutzer besprochen, aber bewusst NICHT von mir umgesetzt — der Nutzer aendert
Archivio (anderes, produktiv laufendes Projekt unter `/Users/fi/archivio`) selbst, separat von dieser
Session. Gesammeltes Wissen fuer naechstes Mal:
  - **Ursache** (siehe oben): `scanner/mail_scanner.py::_strip_signature` schneidet bei IMAP-gescannten
    Mails alles nach der Grussformel ab, bevor der Text in `document_content.content` landet. Der Rohtext
    wird nirgends aufbewahrt (`build_email_record` haelt `raw_text` nur transient im Speicher,
    `save_mail_to_db` persistiert ausschliesslich `cleaned_text`).
  - **Vom Nutzer vorgeschlagene Loesungsansaetze** (beide in Archivio, nicht Rubrica):
    (a) **Empfohlen:** die abgeschnittene Signatur zusaetzlich SEPARAT speichern (neue Spalte/Tabelle in
    Archivios Schema, z. B. `document_content.signature` oder eigene Tabelle) — `content` bleibt fuer
    Archivios eigene Volltextsuche wie bisher signaturbereinigt (kein Rauschen durch wiederkehrende
    Signaturen/Disclaimer), Rubrica koennte die separate Signatur-Spalte gezielt lesen.
    (b) **Einfacher, aber mit Trade-off:** Signatur gar nicht mehr abschneiden, `content` enthaelt
    kuenftig die volle Mail — weniger Aenderungsaufwand, aber Archivios eigene Suche bekommt mehr
    Rauschen (Nutzer: "hinnehmbar").
  - **Reichweite:** wirkt so oder so nur auf KUENFTIG gescannte Mails. Die bereits gescannten 156 Mails
    (nur in der lokalen Mac-Studio-Dev-Instanz, nicht die eigentliche Produktivinstanz auf dem iMac) bleiben
    mit abgeschnittener Signatur — Rohtext ist fuer die bereits verarbeiteten IMAP-Mails nicht mehr
    rekonstruierbar. Der Nutzer wird das Postfach auf dem iMac (Produktivinstanz) zu gegebener Zeit selbst
    neu scannen lassen, nachdem die Archivio-Aenderung dort umgesetzt ist.
  - Sobald das erledigt ist: `archivio_bridge/anbindung.py` muss ggf. angepasst werden, um die neue
    Signatur-Quelle zu lesen (falls Archivio Option (a) waehlt, eine zusaetzliche Spalte in der SQL-Abfrage
    beruecksichtigen statt `_letzte_zeilen(dc.content)`).

- **Visuelles Redesign an Notion angelehnt (2026-07-12):** Nutzer-Feedback: Optik sollte generell mehr wie
  Notion aussehen; ausserdem gemeldeter Layout-Bug ("links viel Abstand, rechts ist der schwarze Balken
  nicht gleich lang wie die Tabelle darunter"). Ursache des Bugs: `nav` spannte die volle Fensterbreite auf,
  `main` war separat mit `max-width:1100px; margin:0 auto` zentriert — auf breiten Bildschirmen liefen beide
  Elemente auseinander. Fix zugleich mit dem Redesign: `base.html` umgebaut auf `.app-shell` (Flex) mit
  **linker globaler Seitenleiste** (`.global-sidebar`, feste Breite 232px, ersetzt den schwarzen Top-Balken)
  + `.app-content` (nimmt den Rest der Breite ein, keine separate Zentrierung mehr) — Sidebar und Inhalt
  spannen dadurch IMMER gemeinsam die volle Fensterbreite auf, der Versatz ist strukturell nicht mehr
  moeglich. Aktive Seite wird serverseitig markiert (`request.url.path` in `base.html`). Farbpalette/
  Typografie an Notion angelehnt (CSS-Variablen in `style.css`: gedeckte Grautoene `--flaeche-sidebar`
  `#fbfbfa`, dezente Rahmen `--rand` `#e9e9e7` statt Schatten, dunkler statt knallblauer Primaerbutton
  `--akzent` `#2f3437`, sekundaere Buttons weiss mit Rahmen). Bestehende Seiten-Layouts (Ordner-Sidebar in
  der Kontaktliste, Modal-Flyover, Ordner-Checkliste) unveraendert in Struktur, nur neu eingefaerbt.
  Alle 72 Tests weiterhin gruen, live verifiziert (Sidebar + aktive Markierung pro Seite, alle bestehenden
  Funktionen/Klassen intakt).

- **Sammel-Bearbeiten, Ordner-Kontext, geschlechtsneutrale Funktionen, Funktion-Combobox (2026-07-12):**
  Vier Punkte aus einem Nutzer-Feedback-Batch:
  - **Mehrfachauswahl + Sammel-Bearbeiten:** Checkbox je Zeile in `contacts_list.html` + "Alle auswaehlen"
    in der Kopfzeile; bei Auswahl erscheint eine `.sammel-leiste` mit "Ausgewählte bearbeiten". Neue Route
    `GET /kontakte/bulk-bearbeiten-flyover?ids=...` (`web/contacts.py`) berechnet je Scalar-Feld
    (`FELDER_MEHRFACHBEARBEITUNG` = vorname/nachname/firma/rolle/kategorie/notizen), ob alle ausgewaehlten
    Kontakte denselben Wert haben (vorausgefuellt) oder nicht ("Unterschiedliche Werte" als Platzhalter,
    Feld bleibt leer + `{feld}__gemischt`-Hidden-Flag). `POST /kontakte/bulk-bearbeiten` wertet das Flag aus:
    war ein Feld gemischt und wird leer abgeschickt, bleibt es je Kontakt unangetastet; war es NICHT
    gemischt (auch wenn der gemeinsame Wert leer war) oder wurde explizit befuellt, gilt der neue Wert fuer
    alle ausgewaehlten Kontakte. Telefonnummern/E-Mails/Adressen/URLs/Ordner bewusst ausgeklammert (kein
    klares Gleich/Verschieden-Konzept bei unterschiedlicher Anzahl je Kontakt, ein Bulk-Replace ueber die
    bestehende `update_kontakt()` waere hier destruktiv). Neue `db.queries.update_kontakt_felder()` fuer das
    partielle Scalar-Update, neues Template `kontakt_bulk_bearbeiten_modal.html`.
  - **Ordner-Kontext bleibt beim Speichern/Loeschen erhalten:** bisher sprang jeder Speichern/Loeschen-Vorgang
    zurueck auf „Alle Kontakte", auch wenn man vorher in einem Ordner gefiltert hatte. Die Bearbeiten-Buttons
    in `contacts_list.html` haengen jetzt `?ordner_id=...` an die Flyover-URL, das Formular traegt es als
    Hidden-Feld `zurueck_ordner_id` durch die Runde, `_liste_url()` in `web/contacts.py` baut daraus die
    Redirect-Ziel-URL (`/kontakte?ordner_id=X` statt `/kontakte`). Gleiches Muster fuer Loeschen.
  - **FUNKTIONEN-Liste geschlechtsneutral:** alle Eintraege in `web/contacts.py::FUNKTIONEN` auf "/in"-Form
    bzw. neutrale Kollektivbegriffe umgestellt (z. B. "Architekt" → "Architekt/in", "Bauherr/Kunde" →
    "Bauherrschaft/Kundschaft").
  - **Funktion-Feld als Combobox mit "Neuer Eintrag erstellen":** natives `<input list><datalist>` konnte
    keine explizite "das gibt es noch nicht, neu anlegen"-Option zeigen. Neue geteilte Vanilla-JS-Komponente
    `web/static/app.js` (`rubricaComboboxInput`/`rubricaComboboxWaehlen`/`rubricaComboboxBlur`), eingebunden
    global ueber `base.html`; Optionen werden als JSON in `data-optionen` auf `.combobox` mitgegeben (ueber
    einen neuen `tojson`-Jinja-Filter in `web/shared.py`, da FastAPIs `Jinja2Templates` anders als Flask
    keinen eingebauten `tojson`-Filter registriert). Tippt man Text ohne Uebereinstimmung, erscheint
    „<Eingabe>" als neuen Eintrag erstellen" als letzter Listeneintrag; Auswahl uebernimmt den Freitext
    unveraendert. Listenelemente werden bewusst per DOM-API (`createElement`/`addEventListener`) statt per
    interpolierten `innerHTML`-Strings aufgebaut, da Optionswerte beliebige Zeichen (Anfuehrungszeichen etc.)
    enthalten koennen, die einen inline `onmousedown="..."`-Attribut-String gebrochen haetten. Eingesetzt in
    `_kontakt_felder.html`, `_kontakt_bearbeiten_form.html` und dem neuen Bulk-Bearbeiten-Modal.
  - 9 neue Tests (Mehrfachauswahl/Sammel-Bearbeiten, Ordner-Kontext, geschlechtsneutrale Liste,
    `update_kontakt_felder`), alle 81 Tests gruen. Live gegen die echte Entwicklungsdatenbank verifiziert
    (Combobox-Markup/-Optionen, Bulk-Flyover-Fragment mit "Unterschiedliche Werte", Hidden-Felder) — kein
    Zugriff auf echte Kontaktdaten in dieser Zusammenfassung, nur Struktur-/Zaehl-Checks.

- **Automatisches Backup an konfigurierbaren Pfad (2026-07-12):** Nutzer-Wunsch — nach jeder Änderung soll
  eine Sicherung z. B. auf ein NAS geschrieben werden. Neues Modul `backup/__init__.py`:
  `sichern_falls_konfiguriert()` liest `backup.pfad` aus den Einstellungen und schreibt bei jedem Aufruf
  EINE Datei (`rubrica-backup.sqlite`, wird jedes Mal überschrieben statt zu akkumulieren) über sqlite3s
  eingebaute `Connection.backup()`-API statt einer rohen Dateikopie — dadurch bleibt der Snapshot auch
  konsistent, falls im selben Moment ein Schreibzugriff läuft (rohes Kopieren der `.sqlite`-Datei könnte
  sonst einen halb geschriebenen Zustand einfrieren). Ausgelöst über eine neue HTTP-Middleware in
  `web/main.py` (`backup_nach_aenderung`): nach jeder erfolgreichen POST-Anfrage (Status < 400) wird die
  Sicherung im Threadpool angestossen (`run_in_threadpool`, damit ein langsamer NAS-Pfad die Event-Loop
  nicht blockiert) — deckt dadurch automatisch ALLE aendernden Routen ab (Kontakte, Ordner, Vorschläge,
  Sammel-Bearbeiten), ohne dass jede Route einzeln angepasst werden musste. Fehlschläge (Pfad nicht
  erreichbar, z. B. NAS offline) werden nur geloggt, nie als Exception nach aussen gereicht — eine normale
  Kontakt-Änderung darf dadurch nicht scheitern. Neues Feld „Backup-Pfad" im Einstellungen-Formular
  (`web/settings.py`, `settings.html`), Default leer = deaktiviert. 5 neue Tests (`tests/test_backup.py`),
  inkl. Middleware-Integrationstest und Fehlerfall mit ungültigem Pfad. Alle 86 Tests grün.

**Zurückgestellt (2026-07-13, vom Nutzer bestätigt „für später notieren"): `.abbu`-Import für andere Büros.**
Ziel: anderen Architekturbüros mit derselben Ausgangslage (Apple-Kontakte statt Rubrica) den Umstieg erleichtern,
indem ihr komplettes Adressbuch-Backup (`.abbu`) direkt importierbar ist. `.abbu` ist kein vCard-Text, sondern
ein macOS-Bundle (Ordner) mit Apples interner, proprietärer SQLite-Datenbank (`AddressBook-v22.abcddb`, Tabellen
wie `ZABCDRECORD` — undokumentiert, ändert sich zwischen macOS-Versionen). Empfehlung, sobald das aufgegriffen
wird: kein eigener `.abbu`-Parser, sondern ein Export-Skript, das per AppleScript aus Kontakte.app heraus nach
vCard exportiert (analog zu `scripts/import_from_contacts_app.py` für den eigenen Bestand) und dieses vcf in
Rubrica importiert — deutlich robuster als das proprietäre Schema direkt zu parsen.

- **Cache-Busting für `style.css`/`app.js` (2026-07-13):** Nach der `.pkg`-Installation auf iMac und Mac Studio
  meldete der Nutzer, das Sammel-Bearbeiten funktioniere zwar, aber "Unterschiedliche Werte" sei nirgends
  sichtbar. Live gegen die echte, frisch installierte Instanz nachgestellt (`curl` gegen
  `/kontakte/bulk-bearbeiten-flyover` mit echten Kontakt-IDs): Server-Output war in Wahrheit korrekt (Platzhalter
  erscheint zuverlässig bei abweichenden Werten) — der wahrscheinlichste Grund ist ein vom Browser gecachtes,
  altes `style.css`/`app.js` unter unveränderter URL nach dem App-Update. Behoben, indem `web/shared.py` die
  `VERSION`-Datei liest und als Jinja-Global `app_version` bereitstellt; `base.html` haengt `?v={{ app_version
  }}` an beide Dateien an, sodass jede neue Version zwangsläufig eine neue URL bekommt und der Browser sie neu
  laden muss.
- **BKP-basierte Funktionsliste (2026-07-13):** Nutzer-Vorlage (reale Adressliste eines Bauprojekts) zeigt, dass
  Büros Kontakte nach Schweizer Baukostenplan (BKP) klassieren (z. B. "297.0 Geometer"). `FUNKTIONEN` in
  `web/contacts.py` komplett durch eine BKP-Liste ersetzt — jeder Eintrag ein String `"<BKP-Nummer>
  <Bezeichnung>"`; die bestehende Combobox-Suche (Teilstring-Filter) findet Eintraege dadurch automatisch sowohl
  über die Nummer ("297") als auch über die Bezeichnung ("geometer"), ohne Code-Änderung an `app.js`. Rollen
  ohne Kostenklassierung (Bauherrschaft, Behörde, intern) bleiben ohne Nummer. Zwei vom Nutzer explizit als
  "Spezialnummern ausserhalb des Standards" genannte Codes (601.x, 701.1) sind trotzdem mit aufgenommen, weil sie
  in der realen Vorlage vorkamen.
- **Export: Gruppierung nach Firma + Sortierung nach BKP-Nummer (2026-07-13):** Bisher listete der PDF/CSV-Export
  jeden Kontakt unabhängig und unsortiert auf. Neu (`export/generator.py`): `_bkp_sortier_schluessel()` sortiert
  numerisch nach BKP-Nummer (nicht alphabetisch, sonst käme "299" vor "297"); Eintraege ohne Nummer zuerst.
  `_gruppiere_fuer_export()` gruppiert zusätzlich nach Firma — mehrere Personen derselben Firma erscheinen als
  ein gemeinsamer Firmenblock (Firmenname/-adresse nur einmal), exakt wie in der vom Nutzer bereitgestellten
  Beispiel-Adressliste (z. B. Astrid Bleuler, Michael Küttel, Corina Moos alle unter "S+K Bauingenieure AG").
  CSV-Zeilen folgen derselben Sortierung (ohne Gruppierung, da Flat-Format). Dass der Export NICHT alle Ordner
  eines Kontakts zeigt, war bereits vorher der Fall (der Generator liest das `projekte`-Feld nirgends) — mit
  einem Test explizit abgesichert. 9 neue Tests, alle 92 Tests grün. Mit synthetischen Testdaten (Struktur wie
  in der Nutzer-Vorlage) visuell gegen ein erzeugtes PDF verifiziert.

- **Menubar-Icon (2026-07-13):** Bisher nur ein Emoji ("📇") als Menubar-Titel. Nutzer hat ein eigenes
  Rubrica-Logo bereitgestellt (`~/Downloads/rubrica_logo_200x200.png`, transparenter Hintergrund) mit der
  Vorgabe "Implementierung gleich wie bei Archivio". Umgesetzt exakt nach Archivio-Vorbild
  (`/Users/fi/archivio/menubar/icon.png`): Logo auf 44×44 skaliert nach `menubar/icon.png`, `RubricaApp`
  (`menubar/app.py`) nutzt jetzt `rumps.App(icon=_ICON, template=True, ...)` statt `title="📇"` -
  `template=True` laesst macOS das Icon fuer Light/Dark-Menubar automatisch farblich invertieren (reines
  Schwarz-auf-transparent, kein separates Dark-Mode-Icon noetig). `scripts/build-pkg.sh` kopiert `icon.png`
  neu mit ins Bundle.
- **Versionsanzeige im Web-UI (2026-07-13):** `app_version` (siehe Cache-Busting oben) wird zusaetzlich unten
  in der Seitenleiste angezeigt ("Rubrica v0.3.0-test") - Nutzer-Wunsch, um auf einen Blick zu sehen, welche
  Version gerade laeuft (relevant bei mehreren Installationen/Maschinen).
- **PDF-Export als echtes Tabellen-Layout + konfigurierbarer Firmenname/Logo (2026-07-13):** Der Block-Stil aus
  der vorherigen Iteration sah laut Nutzer immer noch nicht wie die Vorgabe aus (Screenshot der Original-
  Adressliste erneut geteilt: echte Tabelle mit Spalten BKP Nummer/Unternehmen/Sachbearbeitung/Funktion/
  Telefon-Fax-Direktwahl/Mobil/E-Mail-Webseite, Firmenlogo oben rechts, Firmenname oben mittig). Komplett
  neu gebaut:
  - `export/generator.py::kontakte_pdf()` erzeugt jetzt eine echte reportlab-`Table` im Querformat (A4
    landscape - im Hochformat waeren 7 Spalten zu eng) mit `repeatRows=1` (Kopfzeile wiederholt sich
    automatisch auf jeder Seite). BKP-Nummer/Firma+Adresse erscheinen nur in der ersten Zeile eines
    Firmenblocks (mit `<br/>` nach der Nummer getrennt, sonst bricht reportlab lange Bezeichnungen wie
    "Bauingenieur/in" mitten im Wort um, wenn die Spalte zu schmal ist - siehe `_bkp_zellen_text()`),
    nachfolgende Personen derselben Firma sind eigene Zeilen mit leeren BKP-/Unternehmen-Zellen (nutzt die
    bestehende `_gruppiere_fuer_export()`-Struktur direkt). Telefonnummern werden per `typ` in zwei Spalten
    getrennt (`_telefon_liste(kontakt, mobil=True/False)`) statt wie bisher zusammen mit Typ-Praefix.
  - Firmenname (mittig oben) und Logo (rechts oben, ersetzt den fixen "mmt"-Platzhalter der Vorlage) werden
    per reportlab `onFirstPage`/`onLaterPages`-Canvas-Callback auf JEDER Seite gezeichnet (`_kopf_fuss_zeichner()`)
    - normale Platypus-Flowables wiederholen sich sonst nicht ueber Seitenumbrueche hinweg. Datum + Seitenzahl
      als einfache Fusszeile ebenfalls per Callback. Der Ordnername bleibt alleiniger Titel der Liste
      (Projektname) als normales Flowable am Seitenanfang - unveraendert.
  - Neue Einstellungen (`web/settings.py`, `settings.html`): Freitext „Firmenname" + Logo-Datei-Upload
    (`.png/.jpg/.jpeg/.gif`, gespeichert als `export-logo.<endung>` im Datenverzeichnis via neuem
    `config.settings.daten_verzeichnis()`/`logo_pfad()`, inkl. Vorschau + "Logo entfernen"-Button). Ungueltige
    Dateiendungen werden abgelehnt. `web/export.py` liest beide Werte und reicht sie an den Generator durch.
    Ein fehlendes/ungueltiges Logo darf den Export nie zum Absturz bringen (try/except um `drawImage`).
  - 8 neue Tests (Generator-Spaltenlogik, Einstellungen-Upload/Entfernen/Ablehnung falscher Endungen,
    Export-Route mit konfiguriertem Firmennamen). Alle 100 Tests grün. Mit synthetischen Daten (Struktur wie
    in der Nutzer-Vorlage, inkl. Mehrfachfirma-Block und langer BKP-Bezeichnung) visuell gegen erzeugte PDFs
    verifiziert - Spaltenbreiten iterativ angepasst, bis keine Wort-mitten-im-Wort-Umbrueche mehr auftraten.

- **PDF-Export: Firmenzeile getrennt von Mitarbeiterzeilen, Sichtbarkeits-Einstellungen, echte Trennlinien
  (2026-07-13):** Zweite Vergleichsrunde gegen die Original-Adressliste zeigte drei verbleibende Abweichungen:
  1. **Reale vCard-Importe taggen ueberwiegend englisch/Apple-Style**, nicht deutsch: Stichprobe der
     Produktiv-DB ergab bei Telefonnummern ueberwiegend `work`/`cell`/`home`/`main` statt `arbeit`/`mobil`/
     `privat`, bei E-Mails praktisch nur `internet` (Apple unterscheidet dort gar nicht geschaeftlich/privat).
     Neue Klassierung in `export/generator.py`: `_ist_privat_typ()`/`_ist_mobil_typ()` erkennen beide
     Sprachvarianten (`{"privat","private","home"}` bzw. `{"mobil","cell","iphone"}`); alles andere
     (`work`/`main`/`other`/`arbeit`/unlabeled) gilt als geschaeftlich/allgemein und bleibt sichtbar - so
     verschwinden bei den ueberwiegend `internet`-getaggten E-Mails keine Daten faelschlich.
  2. **Firmenzeile ist jetzt strukturell von den Mitarbeiterzeilen getrennt** (vorher: BKP/Firma in der Zeile
     der ersten Person kombiniert - stimmte nicht mit der Vorlage ueberein, dort hat die Firma immer eine
     eigene Zeile mit Sachbearbeitung/Funktion leer). Ein Kontakt ganz ohne Vor-/Nachname repraesentiert im
     echten Bestand oft die Firma selbst (Sekretariat/allgemeine Nummer) - `_ist_firmenkontakt()` erkennt das
     und liefert die "allgemeine Nummer"/"allgemeine Mail" fuer die Firmenzeile; ist keiner vorhanden, bleiben
     diese Felder leer, die Firmenzeile existiert trotzdem (BKP-Nummer + Firma + Adresse). Adresse zeigt keinen
     Typ-Praefix mehr ("work"/"arbeit" wurde von Nutzer explizit nicht gewuenscht) - nur die optionale
     Privatadresse bekommt "Privat:" vorangestellt, damit sie von der Geschaeftsadresse unterscheidbar bleibt.
  3. **Neue Sichtbarkeits-Einstellungen** (`web/settings.py`, neues Fieldset "Export – sichtbare Felder"):
     vier Checkboxen `mobil_zeigen`/`privates_telefon_zeigen`/`private_email_zeigen`/`privatadresse_zeigen`,
     alle standardmaessig aus (nur geschaeftliche Daten im Export, private/mobile Angaben sind Opt-in). Die
     "Mobil"-Spalte wird bei `mobil_zeigen=False` komplett aus der Tabelle entfernt (nicht nur leer gelassen),
     die restlichen Spalten werden dann automatisch breiter (`_SPALTEN_ANTEILE_OHNE_MOBIL`).
  4. **Echte Trennlinie statt vollem Gitternetz**: Nutzer-Feedback "das Ziel: zwischen jeder BKP eine Linie" -
     das bisherige volle `GRID` (Linien um jede Zelle) ersetzt durch eine duenne `LINEABOVE` genau an den
     Zeilenindizes, an denen eine neue Firmengruppe beginnt (`_tabellenzeilen()` gibt diese Indizes jetzt
     zurueck) - keine Linien mehr zwischen den Mitarbeiterzeilen derselben Firma.
  - Ausserdem: Platzhaltertext beim Firmennamen-Feld war "Strut Architekten AG" (Nutzer: soll bei anderen
    Bueros nicht so erscheinen) → neutrales Beispiel "Muster Architektur AG"; unterstützte Logo-Dateiformate
    (PNG/JPG/JPEG/GIF) jetzt explizit als Hinweistext neben dem Upload-Feld sichtbar.
  - 15 neue/aktualisierte Tests (Typ-Erkennung inkl. englischer Apple-Varianten, Firmenzeile-Trennung,
    Spalten-Ein/Ausblendung, Checkbox-Persistenz inkl. Rueck-auf-False beim Deaktivieren). Alle 109 Tests
    grün. Mit synthetischen Daten (inkl. Firmenkontakt mit allgemeiner Nummer, wie im echten Bestand
    beobachtet) visuell gegen erzeugte PDFs verifiziert, mit und ohne aktivierte Sichtbarkeits-Optionen.

- **Telefon-/E-Mail-Kategorien vereinheitlicht auf Direkt/Privat/Allgemein, Export-Kopf/Fuss verfeinert
  (2026-07-13):** Dritte Vergleichsrunde: Nutzer meldete, dass bei einem Mitarbeiter sowohl geschaeftliche
  als auch private E-Mail im Export erschienen (beide vCard-typisiert als generisches Apple-"internet" -
  keine Unterscheidung anhand des Typs moeglich). Statt die Heuristik weiter zu verfeinern, komplette
  Vereinfachung auf drei nutzerdefinierte Kategorien:
  - `web/contacts.py`: neue Konstante `TELEFON_EMAIL_TYPEN = ["Direkt", "Privat", "Allgemein"]`,
    `_telefon_typ_optionen()`/`_email_typ_optionen()` (gleiches Muster wie `_funktion_optionen()` - Vorschlag
    + bereits im Bestand vorkommende Zusatzwerte). Die Telefon-/E-Mail-Typ-Felder in `_kontakt_felder.html`
    und `_kontakt_bearbeiten_form.html` sind jetzt Comboboxen (wie das Funktion-Feld: Vorschlagsliste +
    Freitext moeglich) statt starrem `<select>` bzw. reinem Freitext. `addRow()` in
    `_kontakt_bearbeiten_form.html` baut die Combobox fuer neu hinzugefuegte Zeilen jetzt per DOM-API auf
    (Optionsliste kommt aus dem `data-optionen`-Attribut des "+ ..."-Buttons), damit dynamisch eingefuegte
    Zeilen dieselbe Kategorisierung anbieten wie die urspruenglich gerenderten.
  - **Migration bestehender Daten** (`db/migrations.py`, `2026-07-13_telefon_email_typ_direkt_privat_allgemein`):
    mappt alte Werte (deutsch: arbeit/mobil/privat/fax; englisch aus Apple-Importen: work/cell/home/main) auf
    die drei neuen Kategorien - Mobilnummern gelten als privat, unbekannte/generische Typen (insbesondere
    Apples "internet" fuer ALLE E-Mails, ohne Unterscheidung) werden konservativ zu "Direkt" (sichtbar), damit
    nichts automatisch verschwindet. **Bekannte Grenze:** Bereits importierte E-Mails, die alle als "internet"
    getaggt sind (praktisch der gesamte Altbestand), koennen dadurch nicht automatisch in geschaeftlich/privat
    unterschieden werden - dafuer muss der Typ pro Kontakt manuell auf "Privat" umgestellt werden, falls eine
    bestimmte Adresse ausgeblendet werden soll. `importer/vcard.py` (`_telefon_typ_normalisieren()`/
    `_email_typ_normalisieren()`) und `importer/signatur.py` wenden dieselbe Kategorisierung neu auf
    KUENFTIGE Importe an.
  - `export/generator.py` entsprechend vereinfacht: keine eigene "Mobil"-Spalte/Einstellung mehr (Mobilnummern
    zaehlen jetzt zur privaten Kategorie und erscheinen zusammen mit anderen privaten Nummern, wenn
    aktiviert) - eine Tabelle mit sechs statt sieben Spalten.
  - **Webseite nur einmal, auf der Firmenzeile:** `_firmen_webseiten_pdf()` sammelt alle URLs innerhalb einer
    Firmengruppe (unabhaengig davon, an welchem Kontakt sie haengen) und zeigt sie nur auf der Firmenzeile -
    vorher wurde sie faelschlich bei jedem Mitarbeiter wiederholt.
  - **Kopf-/Fusszeile verfeinert:** Die Zusammenfassungszeile ("Rubrica – Kontaktliste – N Kontakt(e) –
    erzeugt am ...") entfernt. Fusszeile zeigt jetzt links "Datum / Rubrica", rechts "Seite X von Y" (echte
    Gesamtseitenzahl statt nur der laufenden Nummer) - dafuer neue `_NumberedCanvas`-Klasse (reportlab-
    Standardmuster: Seiten werden zwischengespeichert, bis beim finalen `save()` die Gesamtzahl feststeht).
  - Live-Test des Nutzers zeigte ausserdem einen Kontakt ("Manon Mathys") auf einer separaten Zeile statt im
    selben Firmenblock wie die uebrigen Strut-Mitarbeiter - Ursache war ein Tippfehler im Firmenfeld dieses
    einen Kontakts ("Strut Architeken AG" statt "Strut Architekten AG"); die Gruppierung ist bewusst ein
    exakter Textvergleich (kein Fuzzy-Matching, um nicht versehentlich unterschiedliche Firmen zusammen-
    zulegen) - der Kontakt muss in der Kontaktliste manuell korrigiert werden, kein Code-Fehler.
  - 6 neue Tests (`db/migrations.py`, `importer/vcard.py`-Mapping, Webseite-nur-einmal). Alle 113 Tests grün.

- **Gruppen-Import: Checkbox entfernt, Standardverhalten (2026-07-13):** Nutzer meldete einen "Bug" - beim
  Import eines einzelnen, in Kontakte.app einer Gruppe zugewiesenen Kontakts wurde die Gruppenzuordnung nicht
  uebernommen, obwohl die Checkbox "Gruppen uebernehmen" aktiviert war. Ursache liegt nicht im Rubrica-Code,
  sondern an Apples vCard-Export selbst: Kontakte.app schreibt Gruppenzugehoerigkeit **nur** in die vCard,
  wenn eine ganze Gruppe exportiert wird (dabei entsteht eine zusaetzliche synthetische
  `X-ADDRESSBOOKSERVER-KIND:group`-vCard mit Mitgliederliste) - beim Export eines einzelnen Kontakts fehlt
  diese Information komplett (bereits beim AppleScript-Spike in Abschnitt 9 festgestellt: Gruppenzugehoerigkeit
  ist nur ueber die App-interne Objektbeziehung abrufbar, nicht ueber die vCard-Property). Die Checkbox konnte
  also nichts bewirken, wenn die hochgeladene Datei gar keine Gruppendaten enthielt - kein Fehler in
  `importer/vcard.py`, sondern eine Grenze des Exportformats fuer Einzelkontakte.
  Trotzdem wie gewuenscht umgesetzt: `gruppen_als_ordner`-Checkbox aus `import_form.html` entfernt,
  `importer.vcard.importiere()` versucht Gruppen jetzt standardmaessig zu uebernehmen (`gruppen_als_ordner:
  bool = True`) - kein Risiko, da Ordner-Zuordnung wie alles andere erst als Vorschlag in der Review-Queue
  landet. Bringt fuer den beschriebenen Einzelkontakt-Fall keine Aenderung (die Daten fehlen schlicht), hilft
  aber beim Export ganzer Gruppen (z. B. via `scripts/import_from_contacts_app.py` oder manuellem
  Gruppen-Export), wo die Information vorhanden ist. 1 neuer Test. Alle 114 Tests gruen.

- **Sammel-Leiste nach oben, Ordner-Zuweisung fuer mehrere Kontakte, CSV-Spalten je Kategorie (2026-07-13):**
  Drei weitere Praxis-Rueckmeldungen aus dem Live-Test:
  - Die Sammel-Leiste ("X ausgewaehlt") erschien am Ende der Kontaktliste - bei langen Listen musste man ganz
    nach unten scrollen, um sie zu sehen. In `contacts_list.html` vor die Tabelle verschoben (direkt nach dem
    Filter-Formular); da sie bereits `position: sticky; top: 0` hat (siehe `style.css`), bleibt sie jetzt beim
    Scrollen tatsaechlich sichtbar oben, statt nur am urspruenglichen Ort zu kleben.
  - Neuer Button "Ordner zuweisen" in der Sammel-Leiste: oeffnet eine Liste der bestehenden Ordner
    (`data-ordner` auf der Leiste, per bestehendem `tojson`-Filter), Auswahl ruft fuer jeden ausgewaehlten
    Kontakt den bereits vorhandenen `POST /kontakte/{id}/ordner/{ordner_id}/hinzufuegen`-Endpunkt auf (kein
    neuer Server-Code noetig - nur JS, das den bestehenden Einzel-Endpunkt fuer alle ausgewaehlten IDs
    aufruft). Ergaenzt statt zu ersetzen, wie beim bestehenden Drag&Drop auf einen Ordner.
  - CSV-Export: Telefon/E-Mail/Adresse hatten je eine zusammengefasste Spalte mit allen Eintraegen - jetzt je
    Kategorie (Direkt/Privat/Allgemein) eine eigene Spalte (`_kategorie_von_typ()` ordnet auch alte/englische
    Typwerte einer der drei Kategorien zu), leichter in Excel weiterzuverarbeiten. `_telefon_text()`/
    `_email_text()`/`_adresse_text()` (die alten, zusammengefassten Helfer) entfernt, da nur noch von der CSV
    genutzt.
  - 3 neue Tests. Alle 116 Tests gruen.

- **Sammel-Bearbeiten: Telefon-/E-Mail-Kategorie umstellen (2026-07-13):** Ruckfrage gestellt, wie das
  Sammel-Bearbeiten von Telefonnummern/E-Mails/Adressen mit unterschiedlicher Eintragsanzahl je Kontakt
  funktionieren soll (positionsbasiert? nur Kategorie umstellen? vorerst nicht umsetzen?) - Nutzer entschied
  sich fuer die einfachere, gezielte Loesung: **nur die Kategorie umstellen, nicht die Werte selbst**. Neue,
  von der generischen Sammel-Bearbeiten-Form bewusst getrennte Aktion im Bulk-Modal (`kontakt_bulk_
  bearbeiten_modal.html`): zwei Mini-Formulare ("Telefon: von/auf", "E-Mail: von/auf" mit den drei
  Kategorien), Submit-Buttons tragen ihren `feld`-Wert direkt als `name="feld" value="telefon"` (bzw.
  `"email"`) - eine einzige neue Route `POST /kontakte/bulk-kategorie-umstellen` liest anhand von `feld`,
  welches `{feld}_von`/`{feld}_nach`-Paar gilt. Neue `db.queries.kategorie_umstellen()` (Tabellen-Whitelist
  `{"telefon": "telefonnummern", "email": "emails"}`, kein direktes Interpolieren von Nutzereingaben in den
  Tabellennamen) aendert nur Eintraege mit exakt passendem Ausgangstyp - alle anderen Eintraege (auch
  weitere Telefonnummern/E-Mails desselben Kontakts) bleiben unangetastet. Adresse bewusst nicht
  einbezogen (hat noch keine eigene Direkt/Privat/Allgemein-Combobox im Erfassungsformular). 4 neue Tests
  (DB-Ebene + Web-Route inkl. Ablehnung eines unbekannten `feld`-Werts). Alle 120 Tests gruen.

- **CSS-Fixes Sammel-Leiste (2026-07-13):** Nutzer-Feedback aus dem Live-Test: "Ordner zuweisen"-Dropdown
  zeigte weissen Text auf weissem Hintergrund und hatte einen unpraktischen seitlichen Scroll. Ursache:
  `#ordner-zuweisen-liste` erbte via `.combobox-liste` keine eigene `color` und lag verschachtelt in der
  dunklen `.sammel-leiste` (die `color: #fff` setzt) - die weisse Schriftfarbe kaskadierte nach unten in
  die Liste, die selbst einen weissen/hellen Hintergrund hat. Fix: `.combobox-liste` bekommt eine explizite
  `color: var(--text)` sowie `overflow-x: hidden` und die `<li>`s `white-space: normal; word-break:
  break-word` (statt am schmalen Button-umschliessenden `<span>` zu ueberlaufen). Zusaetzlich bekommt
  `#ordner-zuweisen-liste` eine `min-width: 260px`, da sie an einem sehr schmalen, nur-Button-breiten
  `<span>` haengt und sonst auf dessen Breite gestaucht wird. Ausserdem: den grauen Ordner-"Bubbles"
  (`.tag`) einen unteren Rand (`margin-bottom: 0.3rem`) spendiert, damit mehrere gestapelte Ordner-Tags in
  der Liste nicht mehr direkt aneinanderkleben.

**Pendenz (2026-07-13, unsicher ob gute Loesung, bewusst vorerst belassen):**
  - Sammel-Bearbeiten "Telefon-/E-Mail-Kategorie umstellen" (siehe Eintrag oben): Nutzer ist sich noch nicht
    sicher, ob die gewaehlte UI (zwei separate Mini-Formulare mit von/auf-Auswahl) die beste Loesung ist,
    moechte es aber vorerst so belassen statt sofort zu ueberarbeiten. Bei Gelegenheit erneut mit dem
    Nutzer besprechen, ob eine andere Darstellung (z. B. direkt inline in der Kontaktliste) praktischer waere.

- **Import-Seite: grosse Drag&Drop-Flaeche (2026-07-13):** Das vorherige, unscheinbare
  `<input type="file">` durch eine grosse, klickbare `.import-dropzone` ersetzt (Text "Kontakte hier
  hineinziehen" + Hinweis auf Mehrfachauswahl). Klick auf die Flaeche oeffnet weiterhin den normalen
  Datei-Dialog (`document.getElementById('import-dateien').click()`); Drop setzt `input.files =
  event.dataTransfer.files` direkt am (versteckten) echten File-Input, damit das bestehende Formular/
  die bestehende Route (`web/imports.py`) unveraendert bleiben kann - Mehrfachauswahl/-Drop war durch
  das schon vorhandene `multiple`-Attribut technisch bereits moeglich, war der Nutzerin/dem Nutzer aber
  durch die kleine Flaeche nicht ersichtlich.

- **Review-Queue: Ordner-Auswahlliste, Bearbeiten, Bulk-Aktionen (2026-07-13):**
  - Die bisher rein informativen "Ordner:"-Tags (aus Apple-Gruppen erkannt) bleiben unveraendert bestehen,
    zusaetzlich gibt es pro Vorschlag jetzt eine `.ordner-checkliste` (gleiche Komponente wie im
    Kontakt-Bearbeiten-Formular) mit allen bestehenden Ordnern - Auswahl wird beim Bestaetigen **zusaetzlich**
    zugewiesen (ergaenzend, nicht ersetzend, gleiches Prinzip wie der bestehende "Ordner zuweisen"-Button in
    der Kontaktliste). Umgesetzt ueber einen neuen optionalen Parameter `ordner_ids` in
    `db.queries.bestaetige_vorschlag()`.
  - Neue Sammel-Leiste (erscheint bei Checkbox-Auswahl einzelner Vorschlaege, gleiches Muster wie bei
    Kontakten): Aktionen "Ausgewählte bearbeiten", "Nur ausgewählte bestätigen", "Ausgewählte ablehnen",
    "Auswahl aufheben". Zusaetzlich ein von der Auswahl unabhaengiger "Alle bestätigen"-Button oben auf der
    Seite. Neue Routen `POST /review/bulk-bestaetigen` (ohne `ids` = alle offenen Vorschlaege, mit `ids` =
    nur die uebergebenen) und `POST /review/bulk-ablehnen`.
  - "Bearbeiten" (einzeln oder fuer mehrere ausgewaehlte Vorschlaege) oeffnet ein Modal analog zum
    Sammel-Bearbeiten bei Kontakten - bewusst nur Scalar-Felder (Vorname/Nachname/Firma/Rolle/Funktion/
    Notizen, gleiches `FELDER_MEHRFACHBEARBEITUNG` samt "gemischt"-Logik aus `web/contacts.py`
    wiederverwendet), Telefon/E-Mail/Adresse-Arrays bleiben bewusst unangetastet, da sie erst beim
    Bestaetigen zu echten Kontaktdaten werden (gleiche Scope-Entscheidung wie beim Kontakte-Sammel-
    Bearbeiten). Neue `db.queries.update_vorschlag_rohdaten()` schreibt die Aenderungen direkt ins
    `rohdaten`-JSON zurueck. Neue Routen `GET/POST /review/bulk-bearbeiten(-flyover)`.
  - 8 neue Tests in `tests/test_review_web.py`.

- **Archivio-Import als eigene Seite (2026-07-13):** Die bisher nur ueber einen Link in der Review-Queue
  erreichbare "Archivio-Vorschau" (`web/archivio.py`) ist jetzt eine eigenstaendige Seite unter
  `/archivio-import` (vorher `/review/archivio-vorschau` + Unterrouten) mit eigenem Navigationspunkt
  zwischen "Review-Queue" und "Import". Der Nav-Punkt erscheint nur, wenn `archivio.db_path` in den
  Einstellungen gesetzt **und** die Datei tatsaechlich vorhanden ist (`web/shared.py:
  _archivio_konfiguriert()`, als aufrufbares Jinja-Global `archivio_konfiguriert()` registriert - bewusst
  eine Funktion statt eines einmalig berechneten Werts wie `app_version`, damit eine Aenderung in den
  Einstellungen sofort ohne Neustart wirkt). Der informelle Link in der Review-Queue bleibt zusaetzlich
  bestehen (zeigt jetzt auf `/archivio-import`), ebenfalls nur wenn konfiguriert. Von dort weiterhin
  Uebernahme in die Review-Queue (`quelle='archivio'`), unveraendertes Verhalten.

- **Produktionsbug gefunden + behoben: Loeschen synct nicht zu Radicale (2026-07-13):** Nutzer meldete,
  dass ein in der Weboberflaeche geloeschter Kontakt in Kontakte.app (iMac "windows", Nutzer `pas`)
  bestehen blieb, auch nach erzwungenem Account-Resync. Ferndiagnose anhand von vier vom Nutzer
  bereitgestellten Logs (`server.log`, `radicale.log`, `menubar.log`, `menubar-launcher.log`):
  - Root Cause: `radicale.enabled: false` in der `config.yaml` auf dem iMac - dadurch hat `sync/
    radicale.py::_client()` **jeden** Push (Erstellen UND Loeschen) von Anfang an stillschweigend
    uebersprungen (per Design: Radicale-Fehler duerfen die Web-Route nie blockieren, aber das machte den
    deaktivierten Zustand von aussen ununterscheidbar von "funktioniert einwandfrei, nur eben still").
    Bestaetigt durch: `radicale.log` enthielt in der gesamten Logspanne keine einzige PUT/DELETE-Anfrage
    von Rubricas eigenem httpx-Client (nur Kontakte.app-eigene PROPFIND/REPORT-Sync-Anfragen).
  - Nebenbefund (Ablenkung waehrend der Diagnose, keine Ursache): wiederkehrende "SSL:
    UNEXPECTED_EOF_WHILE_READING"-Fehler alle 15s in `radicale.log` kamen vom Menubar-App-eigenen
    Alive-Check (`menubar/app.py:_radicale_antwortet()`), der bisher nur einen rohen TCP-Connect ohne
    TLS-Handshake machte - Radicale wertete das als abgebrochenen Handshake gegenueber `127.0.0.1` und
    loggte einen Fehler. Behoben durch einen echten HTTPS-Request (Statuscode ist egal, jede Antwort
    zaehlt als "laeuft").
  - **Fix (auf expliziten Nutzerwunsch):** Der `enabled`-Schalter wurde komplett entfernt - Sync ist ab
    sofort immer aktiv, sobald `radicale.base_url` gesetzt ist (kein An/Aus mehr, da ein deaktivierter
    Zustand fuer eine App, deren Zweck der CardDAV-Sync ist, keinen Sinn ergibt und schon zu genau dieser
    Verwirrung gefuehrt hat). `config.yaml.example` entsprechend angepasst.
  - **Radicale-Verbindungsdaten jetzt in der Einstellungen-Seite** (neues Fieldset "CardDAV-Sync
    (Radicale)"): Server-Adresse, Adressbuch-Pfad, Benutzername, Passwort (bewusst als normales
    Klartext-Textfeld, nicht `type="password"` - auf expliziten Nutzerwunsch, da die App nur im internen
    Netz laeuft und hier keine schuetzenswerten Geheimnisse liegen) und TLS-Zertifikatspruefung. Vorher
    war dieser gesamte Konfigurationsblock nur per Hand in `config.yaml` editierbar und dadurch unsichtbar
    fuer den Nutzer - direkte Ursache dafuer, dass ein einmal (vermutlich versehentlich) auf `false`
    gesetzter Schalter niemandem auffiel.
  - 4 neue Tests (`tests/test_radicale_sync.py`, `tests/test_settings_web.py`).
  - **Wichtige Lektion fuers Debugging:** Mac Studio (Nutzer `fi`) ist die Dev-Maschine, iMac "windows"
    (Nutzer `pas`) ist die Produktion - beim Log-Lesen unbedingt zuerst verifizieren, von welcher Maschine
    eine Datei stammt, bevor lokale Dev-Config-Dateien als Referenz herangezogen werden (fruehe
    Fehlspur in dieser Diagnose).

- **Folgebug: Passwortaenderung schrieb htpasswd nicht mit (2026-07-13):** Direkt nach dem vorigen Fix
  meldete der Nutzer, dass Kontakte.app trotz korrekt in den Einstellungen gesetztem Passwort keine
  Verbindung herstellt ("Accountname/Passwort konnte nicht ueberprueft werden"). Ursache: es gibt **zwei**
  Radicale-Passwoerter, die synchron bleiben muessen, und die Einstellungen-Seite pflegte nur eines:
  - `config.yaml -> radicale.password`: das Passwort, das Rubrica als **Client** beim Pushen sendet (und
    das der Nutzer in Kontakte.app eintraegt).
  - `radicale-htpasswd`: die Datei, gegen die der Radicale-**Server** eingehende Logins prueft (Kontakte.app
    UND Rubrica selbst). Wurde bisher nur beim allerersten Start einmalig mit einem Zufallspasswort
    geschrieben (`menubar/app.py:_bereite_radicale_vor()`).
  - Fix: neues Modul `sync/htpasswd.py` mit `set_password()` (bcrypt-Hash, ersetzt den Eintrag desselben
    Benutzers, erhaelt andere) - wird von der Einstellungen-Seite bei jedem Speichern eines Radicale-
    Passworts aufgerufen, sodass Client- und Server-Seite immer uebereinstimmen. Radicale liest die
    htpasswd-Datei pro Anfrage bzw. bei mtime-Aenderung neu ein (verifiziert in
    `radicale/auth/htpasswd.py`), ein Neustart ist nicht noetig. Das bestehende Standalone-Skript
    `scripts/radicale_set_password.py` (das der Menubar-Erststart per subprocess aufruft) delegiert jetzt
    an dasselbe Modul (DRY) und legt dafuer zwei Kandidatenpfade in `sys.path` (Dev-Layout `scripts/` vs.
    flaches Bundle-Layout `Contents/Resources/`), im flachen Bundle-Layout verifiziert.
  - 5 neue Tests (`tests/test_htpasswd.py`, plus htpasswd-Assertion in `tests/test_settings_web.py`).
  - Offener Punkt (nicht kritisch, spaeter): der Menubar-Erststart schreibt das generierte Zufallspasswort
    nur in die htpasswd-Datei und den Zugangsdaten-Merkzettel, nicht in `config.yaml` (dort bleibt es
    zunaechst leer). Fuer den praktischen Ablauf unerheblich, da der Nutzer das Passwort ohnehin in den
    Einstellungen setzt (was jetzt beide Seiten schreibt); ein sauberer Erststart-Flow, der von Anfang an
    ein konsistentes Passwort in beide Ziele schreibt, waere aber die robustere Loesung.

- **Dritter (eigentlicher) Sync-Bug: TLS-Verify gegen lokale CA (2026-07-13):** Nach den beiden vorigen
  Fixes (enabled-Schalter, htpasswd) konnte sich Kontakte.app zwar anmelden, aber neu erstellte Kontakte
  (Test1 unter 0.10, Test2 unter 0.11) tauchten weiterhin nur im Web auf, nicht auf dem Client - und ein
  laengst geloeschter "Test Nutzer" (0.9) blieb sichtbar. Root Cause: Rubricas eigener Push geht an
  `https://127.0.0.1:8443`, dessen Zertifikat von einer lokal erzeugten CA (`radicale-tls/ca-cert.pem`)
  signiert ist. httpx prueft mit `verify=True` gegen den certifi-Trust-Store, der diese CA nicht kennt ->
  **jeder Push schlug mit einem TLS-Zertifikatsfehler fehl, und zwar still** (Sync-Fehler unterbrechen die
  Web-Route bewusst nie). Kontakte.app funktioniert, weil macOS die CA aus dem Schluesselbund vertraut -
  httpx nutzt den Schluesselbund aber nicht.
  - Fix: `sync/radicale.py::_tls_verify()` prueft jetzt gegen die lokale CA-Datei, falls vorhanden (sicher +
    funktioniert), sonst ohne Pruefung (Loopback 127.0.0.1 ist nicht abhoerbar). `verify_ssl=false` erzwingt
    weiterhin keine Pruefung. Damit funktioniert der Push in allen Faellen.
  - Weil dies bereits der DRITTE stille Sync-Fehler in Folge war: neue sichtbare Aktion "Jetzt alles neu
    synchronisieren" auf der Einstellungen-Seite (`POST /einstellungen/radicale-sync` ->
    `radicale.sync_alle()`). Sie pusht alle Kontakte/Ordner neu UND entfernt verwaiste vCards (in Radicale
    vorhanden, aber nicht mehr in der DB - z.B. der alte "Test Nutzer", dessen Delete-Push damals fehlschlug)
    und meldet Anzahlen + erste Fehlermeldung zurueck. `_put`/`_delete`/`push_*` geben dafuer jetzt bool
    (Erfolg) zurueck; neues `_remote_vcf_namen()` listet den Remote-Bestand per PROPFIND (tolerantes Regex auf
    die selbst vergebenen Namen `kontakt-N.vcf`/`projekt-N.vcf`). Das Standalone-Skript
    `scripts/sync_alle_nach_radicale.py` delegiert jetzt an dieselbe Funktion.
  - Erstinstallation (`menubar/app.py`): schreibt das generierte Zufallspasswort jetzt auch in
    `config.yaml` (Client-Seite), nicht nur in htpasswd + Merkzettel - damit Push und Server-Auth von Anfang
    an konsistent sind (schliesst den zuvor als "offener Punkt" notierten Rest).
  - 8 neue Tests (`_tls_verify`, `sync_alle` inkl. Entfernen verwaister Eintraege, Sync-Button-Route).
  - Muster-Lektion: drei Sync-Bugs in Folge blieben nur deshalb so lange unentdeckt, weil Sync-Fehler
    absichtlich still verschluckt werden (damit sie die Web-UI nicht blockieren). Die neue sichtbare
    "Jetzt alles neu synchronisieren"-Rueckmeldung schliesst diese Diagnose-Luecke fuer die Zukunft.

Bekannte Einschränkung: Entwicklungsumgebung läuft unter Python 3.9 (Systemversion) statt der ursprünglich in Abschnitt 6 vermuteten 3.12 — FastAPI-Routenparameter deshalb mit `typing.Optional[int]` statt `int | None` (siehe `CLAUDE.md`). Dies betrifft nur die lokale Entwicklungsumgebung; das produktive `.pkg` bringt sein eigenes Python 3.13 mit und ist davon unabhängig.

Nächste sinnvolle Schritte: Neues `.pkg` (Notion-Redesign + Archivio einzeln übernehmen/ablehnen + Ordner-
Bearbeiten + alle bisherigen Fixes) auf dem iMac installieren; unter „Einstellungen" `archivio.db_path`
setzen, falls Archivio dort genutzt werden soll. Danach: Archivio-Scanner-Anpassung (Signatur separat
speichern, siehe offener Punkt oben) durch den Nutzer selbst, gefolgt von einem Postfach-Rescan auf dem iMac.
