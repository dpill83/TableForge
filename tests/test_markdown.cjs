const assert = require('node:assert/strict');
const {test} = require('node:test');
const {render} = require('../web/js/markdown.js');

test('formats common AI-DM chat Markdown', () => {
  assert.equal(render('**Bold** and *italic*'), '<p><strong>Bold</strong> and <em>italic</em></p>');
  assert.equal(render('# Scene\n\n- First\n- Second'), '<h1>Scene</h1><ul><li>First</li><li>Second</li></ul>');
  assert.equal(render('```\n**literal**\n```'), '<pre><code>**literal**</code></pre>');
  assert.equal(render('\\*\\*literal\\*\\*'), '<p>**literal**</p>');
});

test('escapes message HTML and rejects unsafe links', () => {
  assert.equal(render('<img src=x onerror=alert(1)>'), '<p>&lt;img src=x onerror=alert(1)&gt;</p>');
  assert.equal(render('[click](javascript:alert(1))'), '<p>[click](javascript:alert(1))</p>');
  assert.equal(render('[safe](https://example.com/?a=1&b=2)'),
    '<p><a href="https://example.com/?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">safe</a></p>');
});

const xpTable = `| Opponent | CR | Standard XP |
|---|---:|---:|
| Sahuagin Baron | 5 | 1,800 |
| Tree Blight | 7 | 2,900 |
| Father-Militant Garrick Vael | 13 | 10,000 |
| Ray Pelage | 7 | 2,900 |
| Total monster XP | | 17,600 |`;

test('renders the Ask AI-DM XP table with aligned numeric columns and an empty cell', () => {
  const html = render(xpTable);
  assert.match(html, /tabindex="0" role="region" aria-label="Markdown table"/);
  assert.match(html, /<th scope="col">Opponent<\/th><th scope="col" class="markdown-align-right">CR<\/th>/);
  assert.match(html, /<td>Total monster XP<\/td><td class="markdown-align-right"><\/td><td class="markdown-align-right">17,600<\/td>/);
  assert.equal((html.match(/<tr>/g) || []).length, 6);
});

test('tables support optional border pipes, inline formatting, and all alignments', () => {
  const html = render('Name | Rule | XP\n:--- | :---: | ---:\n**Baron** | `CR 5` | *1,800*');
  assert.match(html, /<th scope="col" class="markdown-align-left">Name<\/th>/);
  assert.match(html, /<th scope="col" class="markdown-align-center">Rule<\/th>/);
  assert.match(html, /<td class="markdown-align-left"><strong>Baron<\/strong><\/td>/);
  assert.match(html, /<td class="markdown-align-center"><code>CR 5<\/code><\/td>/);
  assert.match(html, /<td class="markdown-align-right"><em>1,800<\/em><\/td>/);
});

test('tables handle escaped pipes, missing cells, and extra cells', () => {
  const html = render('| Name | XP |\n| --- | --- |\n| A\\|B |\n| C | 10 | discarded |');
  assert.match(html, /<td>A\|B<\/td><td><\/td>/);
  assert.match(html, /<td>C<\/td><td>10<\/td>/);
  assert.doesNotMatch(html, /discarded/);
  assert.match(render('| Name |\n| --- |\n| end\\| |'), /<td>end\|<\/td>/);
});

test('table boundaries preserve surrounding prose, headings, and fenced code', () => {
  const html = render('Results:\n' + xpTable + '\nAfterward.\n# Next');
  assert.ok(html.startsWith('<p>Results:</p><div'));
  assert.ok(html.endsWith('</div><p>Afterward.</p><h1>Next</h1>'));
  assert.doesNotMatch(render('```\n' + xpTable + '\n```'), /<table>/);
  for (const source of ['A | B\n--- | wrong', 'A | B\n---', 'A | B\n--- | --- | ---', 'Just | prose']) {
    assert.doesNotMatch(render(source), /<table>/);
  }
});

test('table cells escape HTML and allow only safe links', () => {
  const html = render('| Content |\n| --- |\n| <img src=x onerror=alert(1)> |\n| [unsafe](javascript:alert(1)) |\n| [safe](https://example.com) |');
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(html, /<img|href="javascript:/);
  assert.match(html, /href="https:\/\/example.com" target="_blank" rel="noopener noreferrer"/);
});
