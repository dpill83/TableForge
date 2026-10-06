/* Small, safe Markdown subset for saved chat messages. Raw HTML is always text. */
const TableForgeMarkdown = (() => {
  const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));

  const inline = source => {
    let html = '';
    for (let i = 0; i < source.length;) {
      const rest = source.slice(i);
      if (rest[0] === '\\' && /[\\`*_{}\[\]()#+.!>~|\-]/.test(rest[1] || '')) {
        html += escapeHtml(rest[1]); i += 2; continue;
      }
      const code = /^`([^`\n]+)`/.exec(rest);
      if (code) { html += `<code>${escapeHtml(code[1])}</code>`; i += code[0].length; continue; }
      const link = /^\[([^\]\n]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/i.exec(rest);
      if (link) {
        html += `<a href="${escapeHtml(link[2])}" target="_blank" rel="noopener noreferrer">${inline(link[1])}</a>`;
        i += link[0].length; continue;
      }
      let matched = false;
      for (const [mark, tag] of [['**', 'strong'], ['__', 'strong'], ['~~', 'del'], ['*', 'em'], ['_', 'em']]) {
        if (!rest.startsWith(mark)) continue;
        const end = rest.indexOf(mark, mark.length);
        if (end <= mark.length) continue;
        html += `<${tag}>${inline(rest.slice(mark.length, end))}</${tag}>`;
        i += end + mark.length;
        matched = true;
        break;
      }
      if (!matched) { html += escapeHtml(source[i]); i++; }
    }
    return html;
  };

  // Split only unescaped pipes. Remove structural pipe escapes even in code
  // spans, while keeping other escapes for the safe inline renderer.
  const tableCells = line => {
    const cells = [];
    let cell = '', hasPipe = false;
    for (let i = 0; i < line.length; i++) {
      if (line[i] === '\\' && i + 1 < line.length) {
        cell += line[i + 1] === '|' ? line[++i] : line[i] + line[++i];
      } else if (line[i] === '|') {
        cells.push(cell.trim()); cell = ''; hasPipe = true;
      } else cell += line[i];
    }
    cells.push(cell.trim());
    if (hasPipe && cells[0] === '') cells.shift();
    if (hasPipe && cells.at(-1) === '') cells.pop();
    return {cells, hasPipe};
  };
  const tableHeader = (lines, index) => {
    if (index + 1 >= lines.length) return null;
    const header = tableCells(lines[index]);
    const separators = tableCells(lines[index + 1]).cells;
    if (!header.hasPipe || !header.cells.length || header.cells.length !== separators.length ||
        !separators.every(cell => /^:?-+:?$/.test(cell))) return null;
    return {cells: header.cells, alignments: separators.map(cell =>
      cell.startsWith(':') ? (cell.endsWith(':') ? 'center' : 'left') : (cell.endsWith(':') ? 'right' : null))};
  };

  const render = source => {
    const lines = String(source ?? '').replace(/\r\n?/g, '\n').split('\n');
    const out = [];
    const special = line => /^(#{1,6}\s|>\s?|[-*+]\s|\d+[.)]\s|```)/.test(line);
    for (let i = 0; i < lines.length;) {
      if (!lines[i].trim()) { i++; continue; }
      const fence = /^```/.exec(lines[i]);
      if (fence) {
        const code = [];
        i++;
        while (i < lines.length && !/^```\s*$/.test(lines[i])) code.push(lines[i++]);
        if (i < lines.length) i++;
        out.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`);
        continue;
      }
      const heading = /^(#{1,6})\s+(.+)$/.exec(lines[i]);
      if (heading) { out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`); i++; continue; }
      if (/^>\s?/.test(lines[i])) {
        const quote = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ''));
        out.push(`<blockquote>${quote.map(inline).join('<br>')}</blockquote>`);
        continue;
      }
      const bullet = /^\s*([-*+]|\d+[.)])\s+/.exec(lines[i]);
      if (bullet) {
        const ordered = /^\d/.test(bullet[1]);
        const pattern = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
        const items = [];
        while (i < lines.length && pattern.test(lines[i])) items.push(`<li>${inline(lines[i++].replace(pattern, ''))}</li>`);
        const tag = ordered ? 'ol' : 'ul';
        out.push(`<${tag}>${items.join('')}</${tag}>`);
        continue;
      }
      const table = tableHeader(lines, i);
      if (table) {
        const cellHtml = (cell, index, tag) => `<${tag}${tag === 'th' ? ' scope="col"' : ''}${table.alignments[index] ? ` class="markdown-align-${table.alignments[index]}"` : ''}>${inline(cell)}</${tag}>`;
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].trim()) {
          const row = tableCells(lines[i]);
          if (!row.hasPipe) break;
          rows.push(`<tr>${table.cells.map((_, index) => cellHtml(row.cells[index] || '', index, 'td')).join('')}</tr>`);
          i++;
        }
        out.push(`<div class="markdown-table-scroll" tabindex="0" role="region" aria-label="Markdown table"><table><thead><tr>${table.cells.map((cell, index) => cellHtml(cell, index, 'th')).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`);
        continue;
      }
      const paragraph = [];
      while (i < lines.length && lines[i].trim() && (paragraph.length === 0 || (!special(lines[i]) && !tableHeader(lines, i)))) paragraph.push(lines[i++]);
      out.push(`<p>${paragraph.map(inline).join('<br>')}</p>`);
    }
    return out.join('');
  };
  return {render};
})();

if (typeof module !== 'undefined') module.exports = TableForgeMarkdown;
