// @ts-check

// -- Config -------------------------------------------------------------------

/**
 * HTML escape character lookup.
 */
const htmlEscapes = {
    '"': '&quot;',
    '/': '&#x2F;',
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#x27;',
};

// -- Public Functions ---------------------------------------------------------

/**
 * Escapes HTML special characters in a string.
 *
 * @param {string} string
 *
 * @returns {string}
 */
export function escapeHTML(string) {
    return string.replace(/[&<>"'\/]/g, (match) => htmlEscapes[match]);
}
