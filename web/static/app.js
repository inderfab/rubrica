// Gemeinsame Combobox-Komponente fuer das Funktion-Feld (und aehnliche Freitext-
// Auswahlfelder mit Vorschlagsliste). Ersetzt das native <input list><datalist>-
// Muster, weil das keine "Neuer Eintrag erstellen"-Option unterstuetzt.
//
// Erwartetes Markup:
// <div class="combobox" data-optionen='["a", "b"]'>
//     <input type="text" class="combobox-input" oninput="rubricaComboboxInput(event)"
//            onfocus="rubricaComboboxInput(event)" onblur="rubricaComboboxBlur(event)">
//     <ul class="combobox-liste"></ul>
// </div>

function rubricaComboboxInput(event) {
    const input = event.target;
    const wrapper = input.closest('.combobox');
    const liste = wrapper.querySelector('.combobox-liste');
    const optionen = JSON.parse(wrapper.dataset.optionen || '[]');
    const wert = input.value.trim();
    const treffer = wert
        ? optionen.filter(o => o.toLowerCase().includes(wert.toLowerCase()))
        : optionen;
    const exaktTreffer = optionen.some(o => o.toLowerCase() === wert.toLowerCase());

    // Ueber DOM-Elemente statt innerHTML-Strings aufbauen, da Optionen/Freitext
    // beliebige Zeichen (Anfuehrungszeichen etc.) enthalten koennen, die in einem
    // inline onmousedown-Attribut-String die Syntax brechen wuerden.
    liste.replaceChildren();
    for (const option of treffer) {
        const li = document.createElement('li');
        li.textContent = option;
        li.addEventListener('mousedown', (e) => rubricaComboboxWaehlen(e, option));
        liste.appendChild(li);
    }
    if (wert && !exaktTreffer) {
        const li = document.createElement('li');
        li.className = 'combobox-neu';
        li.textContent = `„${wert}" als neuen Eintrag erstellen`;
        li.addEventListener('mousedown', (e) => rubricaComboboxWaehlen(e, wert));
        liste.appendChild(li);
    }

    liste.classList.toggle('sichtbar', liste.childElementCount > 0);
}

function rubricaComboboxWaehlen(event, wert) {
    event.preventDefault();
    const wrapper = event.currentTarget.closest('.combobox');
    const input = wrapper.querySelector('.combobox-input');
    input.value = wert;
    wrapper.querySelector('.combobox-liste').classList.remove('sichtbar');
    input.focus();
}

function rubricaComboboxBlur(event) {
    const wrapper = event.target.closest('.combobox');
    // Verzoegerung, damit ein Klick auf ein <li> (mousedown) vor dem Schliessen
    // der Liste noch verarbeitet wird.
    setTimeout(() => wrapper.querySelector('.combobox-liste').classList.remove('sichtbar'), 150);
}

// Dynamisches Hinzufuegen von Telefon-/E-Mail-/Adress-/URL-Zeilen im gemeinsamen
// Kontakt-Bearbeiten-Formular (_kontakt_bearbeiten_form.html). Bewusst hier in
// app.js statt in einem <script>-Block innerhalb des Formular-Partials: das
// Partial wird teils per htmx (fuehrt eingebettete <script>-Tags beim Swap aus),
// teils per einfachem fetch()+innerHTML= geladen (Archivio-Import) - Letzteres
// fuehrt eingefuegte <script>-Tags NICHT aus, wodurch "addRow" sonst undefiniert
// waere. Als globale Funktion in der immer schon geladenen app.js ist sie in
// beiden Faellen sofort verfuegbar.
//
// "typInput" (tel/mail) rendert statt eines einfachen Textfelds die Combobox
// fuer die Kategorie (Direkt/Privat/Allgemein) - die Optionsliste kommt aus
// dem data-optionen-Attribut des "+ ..."-Buttons (button-Parameter), da neu
// per JS eingefuegte Zeilen die Jinja-Vorlagenwerte sonst nicht kennen.
const ROW_SPECS = {
    tel: {cls: 'tel-row', typInput: 'telefon_typ', fields: [['telefon_nummer', 'Nummer', null]]},
    mail: {cls: 'mail-row', typInput: 'email_typ', fields: [['email_adresse', 'E-Mail', null]]},
    url: {cls: 'mail-row', fields: [['url_typ', 'Typ', '6rem'], ['url_adresse', 'https://…', null]]},
    adr: {cls: 'tel-row', fields: [
        ['adresse_typ', 'Typ', '5rem'], ['adresse_strasse', 'Strasse', null],
        ['adresse_plz', 'PLZ', '4.5rem'], ['adresse_ort', 'Ort', null],
        ['adresse_region', 'Kanton', '5rem'], ['adresse_land', 'Land', '6rem'],
    ]},
};

function addRow(containerId, kind, button) {
    const container = document.getElementById(containerId);
    const spec = ROW_SPECS[kind];
    const row = document.createElement('div');
    row.className = spec.cls;

    if (spec.typInput) {
        const wrapper = document.createElement('div');
        wrapper.className = 'combobox';
        wrapper.style.width = '8rem';
        wrapper.dataset.optionen = (button && button.dataset.optionen) || '[]';
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'combobox-input';
        input.name = spec.typInput;
        input.autocomplete = 'off';
        // Beschriftet und vorbelegt: ein leeres erstes Feld wurde fuer das
        // Nummernfeld gehalten und die Nummer landete in der Kategorie
        // (Nutzer-Feedback). "Privat" als Vorgabe, weil die erste Zeile meist
        // schon die geschaeftliche Nummer traegt.
        input.placeholder = 'Kategorie';
        input.value = 'Privat';
        input.addEventListener('input', rubricaComboboxInput);
        input.addEventListener('focus', rubricaComboboxInput);
        input.addEventListener('blur', rubricaComboboxBlur);
        const liste = document.createElement('ul');
        liste.className = 'combobox-liste';
        wrapper.appendChild(input);
        wrapper.appendChild(liste);
        row.appendChild(wrapper);
    }

    spec.fields.forEach(([name, placeholder, width]) => {
        const feld = document.createElement('input');
        feld.type = 'text';
        feld.name = name;
        feld.placeholder = placeholder;
        if (width) feld.style.width = width;
        row.appendChild(feld);
    });

    const entfernenBtn = document.createElement('button');
    entfernenBtn.type = 'button';
    entfernenBtn.className = 'secondary';
    entfernenBtn.textContent = 'Entfernen';
    entfernenBtn.addEventListener('click', () => row.remove());
    row.appendChild(entfernenBtn);

    container.appendChild(row);
}

// Legt per AJAX einen neuen Ordner an (POST /ordner/neu-ajax), ohne die aktuelle
// Seite/das aktuelle Formular zu verlassen - genutzt an allen Stellen, wo ein
// Ordner ausgewaehlt werden kann (Kontakt-/Vorschlag-Bearbeiten, Postfach-
// Zuordnung, Sammel-Leiste "Ordner zuweisen"). Gibt {id, name} zurueck.
function rubricaOrdnerAnlegen(name) {
    return fetch('/ordner/neu-ajax', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'name=' + encodeURIComponent(name),
    }).then(r => {
        if (!r.ok) throw new Error('Ordner anlegen fehlgeschlagen');
        return r.json();
    });
}

// Legt einen Ordner an und fuegt ihn direkt (angehakt) einer Ordner-Checkliste
// hinzu - genutzt vom Kontakt-/Vorschlag-Bearbeiten-Formular.
function rubricaOrdnerCheckelisteAnlegen(checklisteId, inputId) {
    const input = document.getElementById(inputId);
    const name = input.value.trim();
    if (!name) return;
    rubricaOrdnerAnlegen(name).then(ordner => {
        const checkliste = document.getElementById(checklisteId);
        const hinweis = checkliste.parentElement.querySelector('.empty');
        if (hinweis) hinweis.remove();
        const label = document.createElement('label');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.name = 'ordner_ids';
        checkbox.value = ordner.id;
        checkbox.checked = true;
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(' ' + ordner.name));
        checkliste.appendChild(label);
        input.value = '';
    });
}

// Legt einen Ordner an und fuegt ihn (ausgewaehlt) einem <select>-Dropdown hinzu -
// genutzt bei der Postfach->Ordner-Zuordnung im Archivio-Import.
function rubricaOrdnerSelectAnlegen(selectId) {
    const name = window.prompt('Name des neuen Ordners:');
    if (!name || !name.trim()) return;
    rubricaOrdnerAnlegen(name.trim()).then(ordner => {
        const select = document.getElementById(selectId);
        const option = document.createElement('option');
        option.value = ordner.id;
        option.textContent = ordner.name;
        option.selected = true;
        select.appendChild(option);
    });
}

// Spaltenbreiten in der "Alle Kontakte"-Tabelle per Ziehgriff anpassbar, Breiten
// pro Spalte in localStorage gemerkt. Muss nach jedem htmx-Swap (Suche/Filter
// ersetzt #kontakte-ergebnis komplett) erneut angewendet werden, da das DOM dabei
// neu aufgebaut wird.
const RUBRICA_SPALTENBREITEN_KEY = 'rubrica-kontakte-spaltenbreiten';

function rubricaSpaltenGroessenInitialisieren() {
    const tabelle = document.querySelector('table.kontakte-tabelle');
    if (!tabelle) return;

    let gespeichert = {};
    try { gespeichert = JSON.parse(localStorage.getItem(RUBRICA_SPALTENBREITEN_KEY) || '{}'); } catch (e) {}

    tabelle.querySelectorAll('thead th').forEach((th, index) => {
        if (gespeichert[index]) {
            th.style.width = gespeichert[index] + 'px';
        }
        if (th.querySelector('.col-resize-griff')) return; // schon initialisiert
        const griff = document.createElement('span');
        griff.className = 'col-resize-griff';
        griff.addEventListener('mousedown', (event) => rubricaSpaltenResizeStart(event, th, index));
        th.appendChild(griff);
    });
}

function rubricaSpaltenResizeStart(event, th, index) {
    event.preventDefault();
    const griff = event.currentTarget; // event.currentTarget ist nach dem Dispatch
                                        // wieder null - deshalb hier zwischenspeichern,
                                        // sonst wirft onUp() unten und das Speichern
                                        // in localStorage wird nie erreicht.
    const startX = event.clientX;
    const startBreite = th.offsetWidth;
    griff.classList.add('aktiv');

    function onMove(e) {
        th.style.width = Math.max(40, startBreite + (e.clientX - startX)) + 'px';
    }
    function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        griff.classList.remove('aktiv');
        let gespeichert = {};
        try { gespeichert = JSON.parse(localStorage.getItem(RUBRICA_SPALTENBREITEN_KEY) || '{}'); } catch (e) {}
        gespeichert[index] = th.offsetWidth;
        localStorage.setItem(RUBRICA_SPALTENBREITEN_KEY, JSON.stringify(gespeichert));
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

document.addEventListener('DOMContentLoaded', rubricaSpaltenGroessenInitialisieren);
// app.js wird im <head> geladen, bevor <body> existiert - "document.body...."
// wuerde hier sofort mit TypeError abbrechen und den Listener nie registrieren
// (stiller Fehler: DOMContentLoaded lief noch, aber kein Reapply nach htmx-Swaps).
// "document" existiert dagegen bereits waehrend des Head-Parsings.
document.addEventListener('htmx:afterSettle', rubricaSpaltenGroessenInitialisieren);

// Kontakte.app-Import (Setup-Assistent + Import-Seite): der eigentliche Import
// laeuft im Hintergrund (siehe web/import_status.py), da er bei grossen
// Adressbuechern zehn Minuten und mehr dauert - ein einzelner synchroner Request
// liess sich sonst nicht von einem haengengebliebenen Request unterscheiden
// (genau das war das Feedback aus dem Praxistest). Start-Endpoint gibt sofort
// zurueck, hier wird der Fortschritt per Polling abgefragt.
const RUBRICA_IMPORT_PHASEN_TEXT = {
    lese: 'Lese Kontakte aus Kontakte.app… (kann bei großen Adressbüchern einige Minuten dauern)',
    importiere: 'Importiere',
    synchronisiere: 'Synchronisiere mit Radicale',
};

function rubricaKontakteAppImportStarten(startUrl, statusUrl, knopfId, ergebnisId, navGuardSetter) {
    const knopf = document.getElementById(knopfId);
    const ergebnis = document.getElementById(ergebnisId);
    knopf.disabled = true;
    knopf.textContent = 'Importiere…';
    ergebnis.style.display = 'block';
    ergebnis.style.background = 'var(--bg-hell, #f2f2f2)';
    ergebnis.style.color = '';
    ergebnis.style.fontWeight = 'normal';
    ergebnis.textContent = 'Starte…';
    if (navGuardSetter) navGuardSetter(true);

    fetch(startUrl, { method: 'POST' })
        .then(r => r.json())
        .then(daten => {
            if (!daten.gestartet) {
                ergebnis.textContent = 'Es läuft bereits ein Import (evtl. aus einem anderen Tab) – warte auf Ergebnis…';
            }
            rubricaKontakteAppImportPollen(statusUrl, knopf, ergebnis, navGuardSetter);
        })
        .catch(() => {
            knopf.disabled = false;
            knopf.textContent = 'Aus Kontakte.app importieren';
            if (navGuardSetter) navGuardSetter(false);
            ergebnis.style.fontWeight = 'bold';
            ergebnis.style.background = '#fdecea';
            ergebnis.style.color = '#eb5757';
            ergebnis.textContent = '✗ Start fehlgeschlagen (Netzwerkfehler)';
        });
}

function rubricaKontakteAppImportPollen(statusUrl, knopf, ergebnis, navGuardSetter) {
    fetch(statusUrl)
        .then(r => r.json())
        .then(daten => {
            if (daten.laeuft) {
                let text = RUBRICA_IMPORT_PHASEN_TEXT[daten.phase] || 'Importiere…';
                if (daten.gesamt) text += `: ${daten.verarbeitet} von ${daten.gesamt}`;
                ergebnis.textContent = text;
                setTimeout(() => rubricaKontakteAppImportPollen(statusUrl, knopf, ergebnis, navGuardSetter), 1000);
                return;
            }
            knopf.disabled = false;
            knopf.textContent = 'Aus Kontakte.app importieren';
            if (navGuardSetter) navGuardSetter(false);
            ergebnis.style.fontWeight = 'bold';
            if (daten.fehler_meldung) {
                ergebnis.textContent = '✗ Import fehlgeschlagen (' + daten.fehler_meldung + ')';
                ergebnis.style.background = '#fdecea';
                ergebnis.style.color = '#eb5757';
                return;
            }
            const e = daten.ergebnis || {};
            const typen = e.fehler_typen && Object.keys(e.fehler_typen).length
                ? ' (' + Object.entries(e.fehler_typen).map(([t, n]) => `${n}x ${t}`).join(', ') + ')'
                : '';
            let text = `✓ Import abgeschlossen: ${e.importiert} von ${e.gefunden} Kontakten übernommen, ${e.gruppen_gefunden} Gruppen als Ordner.`;
            if (e.fehler) text += ` ${e.fehler} Einträge übersprungen${typen}.`;
            text += ` Rubrica enthält jetzt insgesamt ${e.kontakte_gesamt} Kontakte.`;
            ergebnis.textContent = text;
            ergebnis.style.background = '#e6f4ea';
            ergebnis.style.color = '#1a7f37';
        })
        .catch(() => {
            setTimeout(() => rubricaKontakteAppImportPollen(statusUrl, knopf, ergebnis, navGuardSetter), 2000);
        });
}
