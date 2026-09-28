// @ts-check

/**
 * @typedef {object} LoaderElements
 * @prop {HTMLElement} loader
 * @prop {HTMLElement} pickBtn
 * @prop {HTMLElement} pasteBtn
 * @prop {HTMLInputElement} fileInput
 * @prop {HTMLTextAreaElement} pasteArea
 */

/**
 * @param {LoaderElements} els
 * @param {(text: string) => void} onText
 */
export function wireJsonFileLoader(els, onText) {
    const { loader, pickBtn, pasteBtn, fileInput, pasteArea } = els;

    pickBtn.addEventListener('click', () => {
        if (pasteArea.classList.contains('show') && pasteArea.value.trim()) {
            onText(pasteArea.value);
        } else {
            fileInput.click();
        }
    });

    pasteBtn.addEventListener('click', () => {
        pasteArea.classList.toggle('show');
        pickBtn.textContent = pasteArea.classList.contains('show') ? 'Load pasted text' : 'Choose file';
        if (pasteArea.classList.contains('show')) {
            pasteArea.focus();
        }
    });

    fileInput.addEventListener('change', (e) => {
        const file = /** @type {HTMLInputElement} */ (e.target).files?.[0];
        if (file) {
            readFileText(file).then(onText);
        }
    });

    for (const ev of ['dragenter', 'dragover']) {
        loader.addEventListener(ev, (e) => {
            e.preventDefault();
            loader.classList.add('drag');
        });
    }

    for (const ev of ['dragleave', 'drop']) {
        loader.addEventListener(ev, (e) => {
            e.preventDefault();
            loader.classList.remove('drag');
        });
    }

    loader.addEventListener('drop', (e) => {
        const file = e.dataTransfer?.files?.[0];
        if (file) {
            readFileText(file).then(onText);
        }
    });
}

/**
 * @param {File} file
 *
 * @returns {Promise<string>}
 */
function readFileText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsText(file);
    });
}

/**
 * @param {string} text
 * @param {{ arrayKey: string, missingMessage: string }} opts
 *
 * @returns {object | null}
 */
export function parseJsonFile(text, { arrayKey, missingMessage }) {
    let parsed;

    try {
        parsed = JSON.parse(text);
    } catch {
        alert("That doesn't look like valid JSON. Check the file and try again.");
        return null;
    }

    if (!parsed[arrayKey] || !Array.isArray(parsed[arrayKey])) {
        alert(missingMessage);
        return null;
    }

    return parsed;
}
