# Rubrica — Testablauf für den manuellen Abnahmetest

Vollständiger Durchlauf von der Installation bis zum Export. Gedacht zum Abhaken:
jeder Punkt ist eine Handlung mit einer klaren Erwartung.

**Stand:** dritter Durchgang mit v1.16.0/1.17.0 durch C und den Anfang von D. Die
offenen Befunde stehen in [Offene Befunde](#offene-befunde). Nächster Schritt: **1.18.0
installieren**, dann C10, C14, C15 und ab D3 weiter.

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
| C10 | 🔁 | Kontakt in Kontakte.app löschen | **Kein Vorschlag mehr.** Der Kontakt taucht nach einigen Minuten von selbst wieder auf — löschen geht nur im Browser | beim letzten Versuch kam er trotz „Behalten“ nicht zurück; mit 1.18.0 nochmals |
| C11 | 🔁 | Denselben Kontakt im Browser löschen | Verschwindet auf allen Geräten und bleibt weg | |
| C12 | ✅ | Kontakt in Kontakte.app anlegen, aber **im privaten Account** (iCloud/„Auf meinem Mac“) | Kommt **nicht** in Rubrica an — Rubrica sieht nur seinen eigenen Account | |
| C13 | ✅ | Nach der Installation einmal **Jetzt alles neu synchronisieren**, dann Vorschläge öffnen | Keine Änderungsvorschläge für Nummern, die niemand angefasst hat | Vorschlagsflut aus 1.14.0 ist weg |
| C14 | 🔁 | Einen **Ordner** in Kontakte.app löschen (falls dort überhaupt möglich) | Der Ordner kommt von selbst zurück — auch Ordner löscht man nur im Browser | in Kontakte.app scheint es gar nicht zu gehen; Punkt bleibt für iPhone o. ä. |
| C15 | 🔁 | Bestehenden Kontakt in Kontakte.app in einen Ordner ziehen, **einige Minuten warten**, dann im Browser einen anderen in denselben Ordner | Beide Zuordnungen bleiben | ohne Wartezeit ging die lokale Zuordnung verloren — siehe Befund „Zeitfenster“ |
| C16 | 🔁 | Vorschlag übernehmen, den Rubrica als **möglichen Duplikat** markiert | Drei Wege: **Zusammenführen**, **Als neuen Kontakt**, **Bestehenden ansehen** | vorher gab es nur Zusammenführen oder den Umweg über Bearbeiten und Speichern |

---

## D — Kategorien für Telefon und E-Mail

| | Status | Handlung | Erwartung |
|---|---|---|---|
| D1 | ✅ | Kontaktformular öffnen, Kategoriefeld anklicken | Reine Auswahlliste, kein freier Text möglich |
| D2 | ✅ | Erste Telefonnummer ausfüllen | Darunter erscheint automatisch eine zweite Zeile mit der nächsten Kategorie |
| D3 | ❌ | In Kontakte.app eine Nummer mit **eigener Bezeichnung** („Sekretariat“) anlegen | Bezeichnung bleibt erhalten und erscheint unter Einstellungen → Kategorien als Wert im Bestand |
| D4 | ⬜ | Diesen Wert dort einer bestehenden Kategorie zuordnen | Alle betroffenen Einträge wechseln die Kategorie |
| D5 | ⬜ | In Kontakte.app eine als **privat** markierte E-Mail anlegen | Landet in Rubrica als „Privat“, nicht als „Direkt“ |
| D6 | ⬜ | Einstellungen → Kategorien: neue Kategorie hinzufügen | Steht danach im Kontaktformular zur Auswahl |
| D7 | ⬜ | Eine Kategorie umbenennen, die in Verwendung ist | Rückfrage mit Anzahl; danach tragen alle betroffenen Einträge den neuen Namen |
| D8 | ⬜ | Eine Kategorie entfernen, die noch benutzt wird | Wird abgelehnt mit Hinweis auf die Anzahl der Einträge |
| D9 | ⬜ | Eine Kategorie ohne Einträge entfernen | Verschwindet aus der Auswahl |
| D10 | ⬜ | Reihenfolge mit den Pfeilen ändern, speichern | Das Kontaktformular schlägt die Kategorien in dieser Reihenfolge vor |
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

**D3 — eigene Kategorie kommt nicht an.** Neuer Kontakt in Kontakte.app mit einer
selbst benannten Kategorie („testkategorie") für eine Telefonnummer: im Vorschlag ist
die Nummer leer und die Kategorie fehlt ganz. Zusätzlich war der Kontakt in
Kontakte.app anschliessend nicht mehr sichtbar.

Zwei mögliche Ursachen, noch nicht auseinandergehalten: die Karteikarte war beim
Einlesen erst halb gefüllt (Kontakte.app lädt sie beim Tippen mehrfach hoch), oder das
eigene Label wird anders abgelegt als erwartet. Für genau diese Frage zeigt der
Bearbeiten-Dialog eines Kontakte.app-Vorschlags ab 1.18.0 die **Karteikarte im
Original** — dort steht schwarz auf weiss, was angekommen ist. Beim nächsten Versuch
bitte einmal aufklappen.

**Zeitfenster bei Ordner-Zuordnungen (C15).** Verschiebt jemand in Kontakte.app einen
Kontakt in einen Ordner und ändert kurz darauf jemand im Browser denselben Ordner,
gewinnt der Browser. Rubrica vergleicht beim Schreiben mit dem Serverstand — eine
Zuordnung, die Kontakte.app noch nicht hochgeladen hat, ist dort nicht sichtbar und
kann deshalb nicht bewahrt werden. Seit 1.17.0 schreibt Rubrica die Mitgliederliste
nur noch bei echter Änderung, das Zeitfenster ist damit klein. Ganz schliessen lässt
es sich nicht. **Praktisch:** Zuordnungen für einen Ordner in einem Durchgang machen.

---

## Behoben in v1.16.0 / v1.17.0 / v1.18.0

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

---

## Offene Wünsche aus dem Test

Keine Fehler, sondern Verbesserungen — noch nicht umgesetzt:

- **Kontakt aus einem Ordner entfernen** geht im Browser nur über Bearbeiten und das
  Häkchen in der Ordnerliste. In Kontakte.app fragt das Löschen „aus Ordner entfernen
  oder löschen?“ mit zwei Knöpfen — dasselbe wäre in der Kontaktliste gewünscht.
- **Adresse mit Kategorie-Auswahl** (Arbeit / Privat / Baustelle) statt fest „Arbeit“.

---

## Wenn etwas nicht ankommt

1. **Einstellungen → Jetzt alles neu synchronisieren** — deckt die meisten Fälle ab.
2. Ein paar Minuten warten: Apples Sync-Dienst entscheidet selbst, wann er läuft.
3. Menüleisten-Symbol prüfen — steht CardDAV auf rot, läuft Radicale nicht.
4. Auf der betroffenen Station: Kontakte.app → Account kurz deaktivieren und wieder aktivieren.
