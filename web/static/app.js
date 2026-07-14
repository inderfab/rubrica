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
// teils per einfachem fetch()+innerHTML= geladen (Review-Queue) - Letzteres
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
