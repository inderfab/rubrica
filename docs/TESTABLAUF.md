# Rubrica — Testablauf für den manuellen Abnahmetest

Vollständiger Durchlauf von der Installation bis zum Export. Gedacht zum Abhaken:
jeder Punkt ist eine Handlung mit einer klaren Erwartung.

**Zwei Rollen im Text:**

- **Browser** = Rubrica-Weboberfläche auf dem Server-Rechner (`http://<rechner>.local:8001`)
- **Kontakte.app** = ein per CardDAV verbundener Mac oder ein iPhone

**Zum Timing:** Apples Sync läuft in eigenem Takt und ist deutlich langsamer als Rubrica.
Rubrica prüft Kontakte.app alle 5 Minuten. Was nicht sofort erscheint, ist meist nicht
kaputt — erst nach ein paar Minuten oder nach **Einstellungen → Jetzt alles neu
synchronisieren** urteilen.

---

## A — Installation und Grundbetrieb

| | Handlung | Erwartung |
|---|---|---|
| A1 | `.pkg` doppelklicken und installieren, während Rubrica noch läuft | Die laufende Instanz wird beendet, die Installation läuft durch |
| A2 | Nach der Installation | Rubrica startet von selbst, ein Browser-Tab öffnet sich, das Symbol erscheint in der Menüleiste |
| A3 | Rechner neu starten und anmelden | Rubrica läuft wieder, ohne dass jemand etwas startet |
| A4 | Im Browser die Kontaktliste öffnen | Alle Kontakte da, Anzahl stimmt |
| A5 | Menüleisten-Symbol anklicken | Web-Oberfläche und CardDAV zeigen beide grün |

---

## B — Arbeiten im Browser (Admin)

| | Handlung | Erwartung |
|---|---|---|
| B1 | Neuen Kontakt anlegen, einem Ordner zuweisen | Erscheint in der Liste; nach einigen Minuten auch in Kontakte.app, in der richtigen Gruppe |
| B2 | Kontakt anlegen und ein Pflichtfeld leer lassen | Speichern wird abgelehnt, das fehlende Feld ist rot markiert |
| B3 | Kontakt anlegen mit Namen, den es schon gibt | Rückfrage „Möglicher Duplikat“ mit der Wahl, den bestehenden zu bearbeiten |
| B4 | Bei einem Kontakt Telefonnummer ändern | Änderung nach einigen Minuten in Kontakte.app sichtbar |
| B5 | Kontakt aus einem Ordner entfernen | Verschwindet in Kontakte.app aus der Gruppe, bleibt aber als Kontakt bestehen |
| B6 | Kontakt im Browser löschen | Verschwindet auch aus Kontakte.app |
| B7 | Neuen Ordner anlegen | Erscheint in Kontakte.app als Gruppe |
| B8 | Ordner umbenennen | Gruppe in Kontakte.app heisst neu, die Mitglieder bleiben |
| B9 | Mehrere Kontakte auswählen → Sammelbearbeiten | Änderung greift bei allen ausgewählten |
| B10 | Kontakt per Drag & Drop auf einen Ordner ziehen | Zuordnung wird übernommen |

---

## C — Arbeiten in Kontakte.app (Mitarbeitende)

Das ist der eigentliche Kern: nichts davon darf Daten in Rubrica überschreiben — alles
kommt zuerst als **Vorschlag**.

| | Handlung | Erwartung |
|---|---|---|
| C1 | Neuen Kontakt in Kontakte.app anlegen (im Rubrica-Account) | Erscheint unter Vorschlägen, nicht direkt in der Liste |
| C2 | Diesen Vorschlag mit **Übernehmen** bestätigen | Wird ein echter Kontakt; die Karteikarte in Kontakte.app bleibt bestehen |
| C3 | Einen Vorschlag **Ablehnen** | Verschwindet aus den Vorschlägen und wird auch in Kontakte.app entfernt |
| C4 | Vorschlag über **Bearbeiten** korrigieren, dann übernehmen | Die korrigierten Werte werden gespeichert, nicht die ursprünglichen |
| C5 | Neue Gruppe in Kontakte.app anlegen | Kommt als Ordner-Vorschlag |
| C6 | Gruppe mit einem bereits bestehenden Kontakt darin anlegen | Nach Bestätigung ist der Kontakt dem neuen Ordner zugeordnet |
| C7 | Bestehenden Kontakt in Kontakte.app in eine andere Gruppe ziehen | Zuordnung landet in Rubrica (ohne Rückfrage — Zuordnungen gelten als unkritisch) |
| C8 | Bei einem bestehenden Kontakt in Kontakte.app die Telefonnummer ändern | Kommt als Änderungsvorschlag, alter und neuer Wert sind gegenübergestellt |
| C9 | Diesen Änderungsvorschlag ablehnen | Rubrica bleibt beim alten Wert und schreibt ihn nach Kontakte.app zurück |
| C10 | Kontakt in Kontakte.app löschen | Kommt als Löschvorschlag — der Kontakt bleibt in Rubrica, bis entschieden ist |
| C11 | Löschvorschlag mit **Behalten** beantworten | Der Kontakt taucht in Kontakte.app wieder auf (kann einige Minuten dauern) |
| C12 | Kontakt in Kontakte.app anlegen, aber **im privaten Account** (iCloud/„Auf meinem Mac“) | Kommt **nicht** in Rubrica an — Rubrica sieht nur seinen eigenen Account |

---

## D — Kategorien für Telefon und E-Mail

| | Handlung | Erwartung |
|---|---|---|
| D1 | Kontaktformular öffnen, Kategoriefeld anklicken | Reine Auswahlliste, kein freier Text möglich |
| D2 | Erste Telefonnummer ausfüllen | Darunter erscheint automatisch eine zweite Zeile mit der nächsten Kategorie |
| D3 | In Kontakte.app eine Nummer mit **eigener Bezeichnung** („Sekretariat“) anlegen | Bezeichnung bleibt erhalten und erscheint unter Einstellungen → Kategorien als Wert im Bestand |
| D4 | Diesen Wert dort einer bestehenden Kategorie zuordnen | Alle betroffenen Einträge wechseln die Kategorie |
| D5 | In Kontakte.app eine als **privat** markierte E-Mail anlegen | Landet in Rubrica als „Privat“, nicht als „Direkt“ |
| D6 | Einstellungen → Kategorien: neue Kategorie hinzufügen | Steht danach im Kontaktformular zur Auswahl |
| D7 | Eine Kategorie umbenennen, die in Verwendung ist | Rückfrage mit Anzahl; danach tragen alle betroffenen Einträge den neuen Namen |
| D8 | Eine Kategorie entfernen, die noch benutzt wird | Wird abgelehnt mit Hinweis auf die Anzahl der Einträge |
| D9 | Eine Kategorie ohne Einträge entfernen | Verschwindet aus der Auswahl |
| D10 | Reihenfolge mit den Pfeilen ändern, speichern | Das Kontaktformular schlägt die Kategorien in dieser Reihenfolge vor |

---

## E — Vorschläge aus E-Mail und Archivio

| | Handlung | Erwartung |
|---|---|---|
| E1 | An das Rubrica-Postfach eine vCard schicken, dann Vorschläge → **Jetzt prüfen** | Kontakt erscheint als Vorschlag mit den Daten aus der vCard |
| E2 | An dasselbe Postfach nur Text schicken (Name, Telefon, Mail) | Wird ebenfalls erkannt |
| E3 | Dieselbe Nachricht ein zweites Mal prüfen lassen | Kein doppelter Vorschlag |
| E4 | Einstellungen → Mail-Eingang → **Verbindung testen** | Meldet Erfolg oder einen verständlichen Fehler |
| E5 | Archivio-Import öffnen | Kandidaten aus den E-Mail-Signaturen erscheinen |
| E6 | Einen Kandidaten übernehmen | Wird ein Kontakt; Kollegen der eigenen Domain tauchen gar nicht erst auf |

---

## F — Import

| | Handlung | Erwartung |
|---|---|---|
| F1 | Eine `.vcf`-Datei per Drag & Drop importieren | Kontakte kommen an, Gruppen aus der Datei werden zu Ordnern |
| F2 | Dieselbe Datei nochmals importieren | Keine Dubletten — Treffer werden erkannt |
| F3 | Import mit unvollständigen Kontakten | Läuft durch (beim Import gelten die Pflichtfelder bewusst nicht) |
| F4 | Danach in der Kontaktliste auf **Unvollständige Kontakte** filtern | Genau diese Datensätze erscheinen |

---

## G — Export

| | Handlung | Erwartung |
|---|---|---|
| G1 | Ordner wählen, alle drei Formate exportieren | ZIP mit PDF, CSV und `.vcf` |
| G2 | PDF öffnen | Firmenname und Logo im Kopf, nach Funktion gruppiert |
| G3 | CSV in Excel öffnen | Eigene Spalte je Kategorie, Umlaute korrekt |
| G4 | Export → Darstellung: **Private Telefonnummer** aktivieren, neu exportieren | Private Nummern erscheinen jetzt im PDF |
| G5 | Dieselbe Einstellung wieder deaktivieren | Sie verschwinden wieder |
| G6 | Nach dem Speichern der Darstellung: Einstellungen prüfen | Mail-Zugangsdaten und Backup-Pfad sind unverändert |
| G7 | `.vcf` per Doppelklick öffnen | Lässt sich in Kontakte.app übernehmen |

---

## H — Mehrere Geräte gleichzeitig

Der Fall, für den die Zusammenführung gebaut ist.

| | Handlung | Erwartung |
|---|---|---|
| H1 | Auf zwei Macs gleichzeitig je einen Kontakt derselben Gruppe hinzufügen | Nach dem Abgleich sind **beide** drin — keiner überschreibt den anderen |
| H2 | Im Browser einen Kontakt einem Ordner zuweisen, während jemand in Kontakte.app einen anderen in dieselbe Gruppe zieht | Beide Zuordnungen bleiben erhalten |
| H3 | Einstellungen → **Jetzt alles neu synchronisieren** | Meldet Anzahl Kontakte, Ordner und entfernte Karteileichen; danach steht dort „Alle … Kontakte werden überwacht“ |
| H4 | Backup-Pfad setzen, dann einen Kontakt ändern | Am Zielort liegt eine frische Kopie der Datenbank |

---

## Wenn etwas nicht ankommt

1. **Einstellungen → Jetzt alles neu synchronisieren** — deckt die meisten Fälle ab.
2. Ein paar Minuten warten: Apples Sync-Dienst entscheidet selbst, wann er läuft.
3. Menüleisten-Symbol prüfen — steht CardDAV auf rot, läuft Radicale nicht.
4. Auf der betroffenen Station: Kontakte.app → Account kurz deaktivieren und wieder aktivieren.
