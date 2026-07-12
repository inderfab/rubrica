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
