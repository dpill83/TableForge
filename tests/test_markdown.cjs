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
