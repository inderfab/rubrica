# Rubrica — Testablauf für den manuellen Abnahmetest

Vollständiger Durchlauf von der Installation bis zum Export. Gedacht zum Abhaken:
jeder Punkt ist eine Handlung mit einer klaren Erwartung.

**Stand:** Abschnitt B und C sind durch bis auf C11 und C17, von D fehlen noch D7–D9 und D11, F5–F7 offen.
Offene Befunde siehe unten. Nächster Schritt: **1.29.1 installieren**.

| Zeichen | Bedeutung |
|---|---|
| ✅ | geprüft und in Ordnung |
| ❌ | geprüft, funktioniert nicht — offen |
| 🔁 | geändert oder unklar — nochmals prüfen |
| ⬜ | noch nicht getestet |

**Zwei Rollen im Text:**

- **Browser** = Rubrica-Weboberfläche auf dem Server-Rechner (`http://<rechner>.local:8001`)
- **Kontakte.app** = ein per CardDAV verbundener Mac oder ein iPhone

**Zum Timing:** Apples Sync läuft in eigenem Takt und ist deutlich langsamer als Rubrica.
Rubrica prüft Kontakte.app alle 5 Minuten. Was nicht sofort erscheint, ist meist nicht
kaputt — erst nach ein paar Minuten oder nach **Einstellungen → Jetzt alles neu
synchronisieren** urteilen.

---

## A — Installation und Grundbetrieb

| | Status | Handlung | Erwartung | Befund |
|---|---|---|---|---|
| A1 | ✅ | `.pkg` doppelklicken und installieren, während Rubrica noch läuft | Die laufende Instanz wird beendet, danach läuft **genau eine** Instanz (ein Symbol in der Menüleiste) | 1.15.0 in Ordnung |
| A2 | 🔁 | Nach der Installation | Rubrica startet von selbst, Symbol in der Menüleiste. **Kein** Browser-Tab (nur bei einer frischen Installation) | Start in Ordnung; Verhalten beim nächsten Rechner-Neustart noch beobachten |
| A3 | ✅ | Rechner neu starten und anmelden | Rubrica läuft wieder, ohne dass jemand etwas startet | 1× Rubrica startet korrekt (Archivio startet doppelt — anderes Projekt) |
| A4 | ✅ | Im Browser die Kontaktliste öffnen | Alle Kontakte da, Anzahl stimmt | |
| A5 | ✅ | Menüleisten-Symbol anklicken | Web-Oberfläche und CardDAV zeigen beide grün | |

---

## B — Arbeiten im Browser (Admin)

| | Status | Handlung | Erwartung |
|---|---|---|---|
| B1 | ✅ | Neuen Kontakt anlegen, einem Ordner zuweisen | Erscheint in der Liste; nach einigen Minuten auch in Kontakte.app, in der richtigen Gruppe |
| B2 | ✅ | Kontakt anlegen und ein Pflichtfeld leer lassen | Speichern wird abgelehnt, das fehlende Feld ist rot markiert |
| B3 | ✅ | Kontakt anlegen mit Namen, den es schon gibt | Rückfrage „Möglicher Duplikat“ mit der Wahl, den bestehenden zu bearbeiten |
| B4 | ✅ | Bei einem Kontakt Telefonnummer ändern | Änderung nach einigen Minuten in Kontakte.app sichtbar |
| B5 | ✅ | Kontakt aus einem Ordner entfernen | Verschwindet in Kontakte.app aus der Gruppe, bleibt aber als Kontakt bestehen |
| B6 | ✅ | Kontakt im Browser löschen | Verschwindet auch aus Kontakte.app |
| B7 | ✅ | Neuen Ordner anlegen | Erscheint in Kontakte.app als Gruppe |
| B8 | ✅ | Ordner umbenennen | Gruppe in Kontakte.app heisst neu, die Mitglieder bleiben |
| B9 | ✅ | Mehrere Kontakte auswählen → Sammelbearbeiten | Änderung greift bei allen ausgewählten |
| B10 | ✅ | Kontakt per Drag & Drop auf einen Ordner ziehen | Zuordnung wird übernommen |
| B11 | ✅ | Kontakt anlegen, der **nur eine Firma** ist (Namensfelder leer) | Lässt sich speichern; als Bezeichnung genügt Name **oder** Firma | neu ab 1.20.0 |
| B12 | ✅ | Bei einem Kontakt die Adresse ändern und speichern, dann **Verlauf** öffnen | Neuer Eintrag mit Zeitpunkt, Quelle „Bearbeitet im Browser“, altem und neuem Wert | neu ab 1.27.0 |
| B13 | ✅ | Bei diesem Verlaufseintrag **Rückgängig** klicken | Vorschau zeigt den alten Wert orange markiert; erst „Speichern“ setzt ihn zurück, „Abbrechen“ ändert nichts | neu ab 1.27.0 |
| B14 | ✅ | Bei einem Kontakt **+ Funktion** klicken, zweites Funktion/Rolle-Paar ausfüllen, speichern | Beide Paare bleiben erhalten, erscheinen beim erneuten Öffnen wieder | neu ab 1.28.0 |
| B15 | ✅ | Diesen Kontakt exportieren (PDF/CSV) | Erscheint unter **beiden** Funktionen, mit der jeweils passenden Rolle | neu ab 1.28.0 |
| B16 | ✅ | Einstellungen → **Verlauf aller Kontakte** öffnen | Zeigt Änderungen quer über alle Kontakte, neueste zuerst, mit Link zum Kontakt und „Rückgängig“ | neu ab 1.28.0 |

---

## C — Arbeiten in Kontakte.app (Mitarbeitende)

Das ist der eigentliche Kern: nichts davon darf Daten in Rubrica überschreiben — alles
kommt zuerst als **Vorschlag**.

| | Status | Handlung | Erwartung | Befund |
|---|---|---|---|---|
| C1 | ✅ | Neuen Kontakt in Kontakte.app **direkt in einem Ordner** anlegen | Erscheint **einmal** unter Vorschlägen, mit allen Feldern **und mit dem Ordner** | |
| C2 | ✅ | Diesen Vorschlag mit **Übernehmen** bestätigen | Wird ein echter Kontakt **im richtigen Ordner** | |
| C3 | ✅ | Einen Vorschlag **Ablehnen** | Verschwindet aus den Vorschlägen und wird auch in Kontakte.app entfernt | |
| C4 | ✅ | Vorschlag über **Bearbeiten** korrigieren, dann übernehmen | Die korrigierten Werte werden gespeichert, nicht die ursprünglichen | |
| C5 | ✅ | Neue Gruppe in Kontakte.app anlegen | Kommt als Ordner-Vorschlag | |
| C6 | ✅ | Gruppe mit einem bereits bestehenden Kontakt darin anlegen | Nach Bestätigung ist der Kontakt dem neuen Ordner zugeordnet | |
| C7 | ✅ | Bestehenden Kontakt in Kontakte.app in eine andere Gruppe ziehen | Zuordnung landet in Rubrica (ohne Rückfrage — Zuordnungen gelten als unkritisch) | |
| C8 | ✅ | Bei einem bestehenden Kontakt in Kontakte.app die Telefonnummer ändern | Kommt als Änderungsvorschlag, alter und neuer Wert sind gegenübergestellt | |
| C9 | ✅ | Diesen Änderungsvorschlag ablehnen | Rubrica bleibt beim alten Wert und schreibt ihn nach Kontakte.app zurück | |
| C10 | ✅ | Kontakt in Kontakte.app löschen | **Kein Vorschlag mehr.** Der Kontakt taucht nach einigen Minuten von selbst wieder auf — löschen geht nur im Browser | |
| C11 | 🔁 | Denselben Kontakt im Browser löschen | Verschwindet auf allen Geräten und bleibt weg | |
| C12 | ✅ | Kontakt in Kontakte.app anlegen, aber **im privaten Account** (iCloud/„Auf meinem Mac“) | Kommt **nicht** in Rubrica an — Rubrica sieht nur seinen eigenen Account | |
| C13 | ✅ | Nach der Installation einmal **Jetzt alles neu synchronisieren**, dann Vorschläge öffnen | Keine Änderungsvorschläge für Nummern, die niemand angefasst hat | Vorschlagsflut aus 1.14.0 ist weg |
| C14 | ✅ | Einen **Ordner** in Kontakte.app löschen (falls dort überhaupt möglich) | Der Ordner kommt von selbst zurück — auch Ordner löscht man nur im Browser | in Kontakte.app nicht möglich (bestätigt) — Löschen bleibt ohnehin nur im Browser vorgesehen |
| C15 | ✅ | Bestehenden Kontakt in Kontakte.app in einen Ordner ziehen, **einige Minuten warten**, dann im Browser einen anderen in denselben Ordner | Beide Zuordnungen bleiben | gleichzeitig gewinnt weiterhin der Browser — bekannte Grenze, siehe Befund „Zeitfenster“ |
| C16 | ✅ | Vorschlag übernehmen, den Rubrica als **möglichen Duplikat** markiert | Drei Wege: **Zusammenführen**, **Als neuen Kontakt**, **Bestehenden ansehen** | |
| C17 | ⬜ | Einen Duplikat-Vorschlag **Zusammenführen**, bei dem der bestehende Kontakt einen Namen hat | Der Name des bestehenden Kontakts bleibt; nur Nummern, Adressen und Mails kommen dazu | neu ab 1.19.0 — genau hier gingen Kontakte verloren |
| C18 | ✅ | In Kontakte.app eine Adresse/Nummer ändern, **bevor** der Vorschlag bestätigt ist **Einstellungen → Jetzt alles neu synchronisieren** klicken | Der Vorschlag bleibt mit dem geänderten Wert stehen — wird **nicht** stillschweigend mit dem alten Stand überschrieben | neu ab 1.26.0 — siehe Offene Befunde |

---

## D — Kategorien für Telefon und E-Mail

| | Status | Handlung | Erwartung |
|---|---|---|---|
| D1 | ✅ | Kontaktformular öffnen, Kategoriefeld anklicken | Reine Auswahlliste, kein freier Text möglich |
| D2 | ✅ | Erste Telefonnummer ausfüllen | Darunter erscheint automatisch eine zweite Zeile mit der nächsten Kategorie |
| D3 | ✅ | In Kontakte.app eine Nummer mit **eigener Bezeichnung** („Sekretariat“) anlegen | Bezeichnung bleibt erhalten und erscheint unter Einstellungen → Kategorien als Wert im Bestand |
| D4 | ✅ | Diesen Wert dort einer bestehenden Kategorie zuordnen | Alle betroffenen Einträge wechseln die Kategorie |
| D5 | ✅ | In Kontakte.app eine als **privat** markierte E-Mail anlegen | Landet in Rubrica als „Privat“, nicht als „Direkt“ |
| D6 | ✅ | Einstellungen → Kategorien: neue Kategorie hinzufügen | Steht danach im Kontaktformular zur Auswahl |
| D7 | ⬜ | Eine Kategorie umbenennen, die in Verwendung ist | Rückfrage mit Anzahl; danach tragen alle betroffenen Einträge den neuen Namen |
| D8 | ⬜ | Eine Kategorie entfernen, die noch benutzt wird | Wird abgelehnt mit Hinweis auf die Anzahl der Einträge |
| D9 | ⬜ | Eine Kategorie ohne Einträge entfernen | Verschwindet aus der Auswahl |
| D10 | ✅ | Reihenfolge mit den Pfeilen ändern, speichern | Das Kontaktformular schlägt die Kategorien in dieser Reihenfolge vor |
| D11 | ⬜ | In Kontakte.app die Kategorie einer Nummer ansehen, die in Rubrica „Privat Handy“ heisst | Kontakte.app zeigt „Privat Handy“ im Klartext als Bezeichnung |

---

## E — Vorschläge aus E-Mail und Archivio

| | Status | Handlung | Erwartung |
|---|---|---|---|
| E1 | ⬜ | An das Rubrica-Postfach eine vCard schicken, dann Vorschläge → **Jetzt prüfen** | Kontakt erscheint als Vorschlag mit den Daten aus der vCard |
| E2 | ⬜ | An dasselbe Postfach nur Text schicken (Name, Telefon, Mail) | Wird ebenfalls erkannt |
| E3 | ⬜ | Dieselbe Nachricht ein zweites Mal prüfen lassen | Kein doppelter Vorschlag |
| E4 | ⬜ | Einstellungen → Mail-Eingang → **Verbindung testen** | Meldet Erfolg oder einen verständlichen Fehler |
| E5 | ⬜ | Archivio-Import öffnen | Kandidaten aus den E-Mail-Signaturen erscheinen |
| E6 | ⬜ | Einen Kandidaten übernehmen | Wird ein Kontakt; Kollegen der eigenen Domain tauchen gar nicht erst auf |

---

## F — Import

| | Status | Handlung | Erwartung |
|---|---|---|---|
| F1 | ⬜ | Eine `.vcf`-Datei per Drag & Drop importieren | Kontakte kommen an, Gruppen aus der Datei werden zu Ordnern |
| F2 | ⬜ | Dieselbe Datei nochmals importieren | Keine Dubletten — Treffer werden erkannt |
| F3 | ⬜ | Import mit unvollständigen Kontakten | Läuft durch (beim Import gelten die Pflichtfelder bewusst nicht) |
| F4 | ⬜ | Danach in der Kontaktliste auf **Unvollständige Kontakte** filtern | Genau diese Datensätze erscheinen |
| F5 | ⬜ | Import abschliessen | Ergebnisseite nennt **wie viele neu** und **wie viele zusammengeführt** wurden, beide Listen namentlich |
| F6 | ⬜ | Import mit **Immer als neue Kontakte anlegen** wiederholen | Nichts wird zusammengeführt, jede Karte wird ein eigener Kontakt |
| F7 | ⬜ | Einstellungen → **Bestand aufräumen** öffnen | Zeigt Namensdubletten und mehrfach verwendete Angaben; „Löschen" bzw. „Hier entfernen" wirkt nur auf den gewählten Eintrag |

---

## G — Export

| | Status | Handlung | Erwartung |
|---|---|---|---|
| G1 | ⬜ | Ordner wählen, alle drei Formate exportieren | ZIP mit PDF, CSV und `.vcf` |
| G2 | ⬜ | PDF öffnen | Firmenname und Logo im Kopf, nach Funktion gruppiert |
| G3 | ⬜ | CSV in Excel öffnen | Eigene Spalte je Kategorie, Umlaute korrekt |
| G4 | ⬜ | Export → Darstellung: **Private Telefonnummer** aktivieren, neu exportieren | Private Nummern erscheinen jetzt im PDF |
| G5 | ⬜ | Dieselbe Einstellung wieder deaktivieren | Sie verschwinden wieder |
| G6 | ⬜ | Nach dem Speichern der Darstellung: Einstellungen prüfen | Mail-Zugangsdaten und Backup-Pfad sind unverändert |
| G7 | ⬜ | `.vcf` per Doppelklick öffnen | Lässt sich in Kontakte.app übernehmen |

---

## H — Mehrere Geräte gleichzeitig

Der Fall, für den die Zusammenführung gebaut ist.

| | Status | Handlung | Erwartung |
|---|---|---|---|
| H1 | ⬜ | Auf zwei Macs gleichzeitig je einen Kontakt derselben Gruppe hinzufügen | Nach dem Abgleich sind **beide** drin — keiner überschreibt den anderen |
| H2 | ⬜ | Im Browser einen Kontakt einem Ordner zuweisen, während jemand in Kontakte.app einen anderen in dieselbe Gruppe zieht | Beide Zuordnungen bleiben erhalten |
| H3 | ⬜ | Einstellungen → **Jetzt alles neu synchronisieren** | Meldet Anzahl Kontakte, Ordner und entfernte Karteileichen; danach steht dort „Alle … Kontakte werden überwacht“ |
| H4 | ⬜ | Backup-Pfad setzen, dann einen Kontakt ändern | Am Zielort liegt eine frische Kopie der Datenbank |

---

## Offene Befunde

**Zusammengeführte Kontakte aus dem Bestand (ausserhalb des Testablaufs).** Zwei
Personen derselben Firma wurden zu einer zusammengefasst, die zweite fehlt seither.
Ursache gefunden und in 1.19.0 behoben: beim Zusammenführen gewann der Name aus dem
Vorschlag und überschrieb den bestehenden Kontakt. Was bereits verloren ging, findet
`scripts/fehlende_kontakte.py` — Vergleich der alten vCard-Exporte gegen die
Datenbank, fehlende Kontakte werden als einzelne Karten herausgeschrieben.

**Voll-Sync überschrieb offene Änderungen (ausserhalb des Testablaufs).** Eine in
Kontakte.app korrigierte Adresse stand hinterher wieder auf dem alten Wert, ohne dass
jemand bewusst abgelehnt hatte. Ursache gefunden und in 1.26.0 behoben: **Jetzt alles
neu synchronisieren** erkannte die Änderung zwar als Vorschlag, pushte im selben
Durchlauf aber trotzdem jeden Kontakt unbedingt aus der Datenbank zurück — die
Korrektur wurde augenblicklich wieder überschrieben, der jetzt gegenstandslose
Vorschlag beim nächsten Abgleich automatisch als „abgelehnt“ zurückgezogen. Betroffene
Fälle im produktiven Bestand mit `scripts/pruefe_verworfene_aenderungen.py` geprüft.

**Zeitfenster bei Ordner-Zuordnungen (C15).** Verschiebt jemand in Kontakte.app einen
Kontakt in einen Ordner und ändert kurz darauf jemand im Browser denselben Ordner,
gewinnt der Browser. Rubrica vergleicht beim Schreiben mit dem Serverstand — eine
Zuordnung, die Kontakte.app noch nicht hochgeladen hat, ist dort nicht sichtbar und
kann deshalb nicht bewahrt werden. Seit 1.17.0 schreibt Rubrica die Mitgliederliste
nur noch bei echter Änderung, das Zeitfenster ist damit klein. Ganz schliessen lässt
es sich nicht. **Praktisch:** Zuordnungen für einen Ordner in einem Durchgang machen.

---

## Behoben in v1.16.0 bis v1.19.0

- **Vorschlag kam doppelt** — Dublettenschutz vergleicht jetzt auch den Inhalt, nicht
  nur den Dateinamen. Die zweite Karte hängt am Vorschlag und wird mitentfernt.
- **Ordner-Zuordnung fehlte** — fremde Mitglieder bleiben in der Gruppe stehen,
  solange ihr Vorschlag offen ist.
- **Duplikat-Verdacht war nicht ablehnbar** — neben „Zusammenführen" gibt es jetzt
  „Als neuen Kontakt". Anlass: ein Testkontakt wurde wegen einer gemeinsamen
  Zentralennummer mit einer Firma zusammengeführt und stand danach mit deren
  sämtlichen Nummern da.
- **Löschen** — Kontakte *und* Ordner werden zurückgeschrieben, wenn sie in
  Kontakte.app verschwinden. Gelöscht wird ausschliesslich im Browser.
- **Zusammenführen überschrieb den Namen** — der bestehende Kontakt behält seinen
  Namen; nur ein namenloser Firmeneintrag bekommt den Namen aus dem Vorschlag.
- **Eigene Kategorie aus Kontakte.app** (D3) — funktioniert; im Bearbeiten-Dialog
  lässt sich zusätzlich die Karteikarte im Original aufklappen.

---

## Offene Wünsche aus dem Test

Keine Fehler, sondern Verbesserungen — noch nicht umgesetzt:

- **Kontakt aus einem Ordner entfernen** geht im Browser nur über Bearbeiten und das
  Häkchen in der Ordnerliste. In Kontakte.app fragt das Löschen „aus Ordner entfernen
  oder löschen?“ mit zwei Knöpfen — dasselbe wäre in der Kontaktliste gewünscht.

---

## Wenn etwas nicht ankommt

1. **Einstellungen → Jetzt alles neu synchronisieren** — deckt die meisten Fälle ab.
2. Ein paar Minuten warten: Apples Sync-Dienst entscheidet selbst, wann er läuft.
3. Menüleisten-Symbol prüfen — steht CardDAV auf rot, läuft Radicale nicht.
4. Auf der betroffenen Station: Kontakte.app → Account kurz deaktivieren und wieder aktivieren.
