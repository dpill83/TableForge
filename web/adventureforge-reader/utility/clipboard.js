// @ts-check

/**
 * @param {string} text
 *
 * @returns {Promise<void>}
 */
function copyFallback(text) {
    return new Promise((resolve, reject) => {
        let ta = document.createElement('textarea');

        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.cssText = 'position:fixed;top:0;left:0;width:2em;height:2em;padding:0;border:none;outline:none;box-shadow:none;background:transparent';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, text.length);

        try {
            let ok = document.execCommand('copy');

            document.body.removeChild(ta);
            ok ? resolve() : reject(new Error('execCommand failed'));
        } catch (err) {
            document.body.removeChild(ta);
            reject(err);
        }
    });
}

/**
 * @param {string} text
 *
 * @returns {Promise<void>}
 */
export function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text).catch(() => copyFallback(text));
    }

    return copyFallback(text);
}

/**
 * @param {HTMLElement} btn
 * @param {boolean} ok
 */
export function flashCopied(btn, ok) {
    if (!btn.dataset.origLabel) {
        btn.dataset.origLabel = btn.textContent || '';
    }

    btn.textContent = ok ? 'Copied ✓' : 'Copy failed';
    btn.classList.toggle('done', ok);
    btn.classList.toggle('fail', !ok);

    setTimeout(() => {
        btn.textContent = btn.dataset.origLabel;
        btn.classList.remove('done', 'fail');
    }, ok ? 2000 : 3000);
}
