const { test } = require('node:test');
const assert = require('node:assert/strict');
const { extractPlayerView, formatReplies, validURL } = require('../tableforge.user.js');

test('DM extraction excludes all surrounding private notes', () => {
  const raw = 'Secret: the butler is a devil.\n[PLAYER_VIEW]\nA butler greets you.\n[/PLAYER_VIEW]\nSecret DC 20';
  assert.equal(extractPlayerView(raw), 'A butler greets you.');
});

test('DM extraction preserves multiple public blocks in order, including Unicode', () => {
  assert.equal(extractPlayerView('private [PLAYER_VIEW]“Welcome,” he says. 🐉[/PLAYER_VIEW] hidden [PLAYER_VIEW]The door shuts.\nYou hear a bell.[/PLAYER_VIEW]'),
    '“Welcome,” he says. 🐉\n\nThe door shuts.\nYou hear a bell.');
});

test('missing, incomplete, reversed, empty and nested tags are rejected', () => {
  for (const text of [
    'Private response without public tags.',
    '[PLAYER_VIEW]Still streaming',
    '[/PLAYER_VIEW]secret[PLAYER_VIEW]',
    '[PLAYER_VIEW] \n [/PLAYER_VIEW]',
    '[PLAYER_VIEW]outer [PLAYER_VIEW]inner[/PLAYER_VIEW][/PLAYER_VIEW]',
    '[PLAYER_VIEW]Public[/PLAYER_VIEW] [PLAYER_VIEW]Unfinished',
    '[PLAYER_VIEW]Public[/PLAYER_VIEW] stray [/PLAYER_VIEW]',
    '[player_view]Wrong case[/player_view]'
  ]) assert.throws(() => extractPlayerView(text), Error, text);
});

test('groups interleaved contributions by participant while preserving each reply', () => {
  const replies = [
    { id: 1, actor_id: 'g', name: 'George', text: 'I listen.' },
    { id: 2, actor_id: 'v', name: 'Viktor', text: 'I open the door.' },
    { id: 3, actor_id: 'g', name: 'George', text: 'And ready my shield.' }
  ];
  const output = formatReplies(42, replies);
  assert.ok(output.includes('SCENE #42'));
  assert.ok(output.includes('## George\n[Reply #1]\nI listen.\n\n[Reply #3]\nAnd ready my shield.'));
  assert.ok(output.includes('## Viktor\n[Reply #2]\nI open the door.'));
  assert.equal((output.match(/## George/g) || []).length, 1);
});

test('relay URL accepts HTTPS and loopback HTTP, retaining proxy prefixes', () => {
  assert.equal(validURL('https://relay.example.com/tableforge/'), 'https://relay.example.com/tableforge');
  assert.equal(validURL('http://127.0.0.1:8787/'), 'http://127.0.0.1:8787');
  assert.equal(validURL('http://localhost:8787'), 'http://localhost:8787');
  assert.equal(validURL('http://[::1]:8787'), 'http://[::1]:8787');
});

test('relay URL rejects cleartext remote hosts, embedded credentials and URL suffix tricks', () => {
  for (const url of ['http://relay.example.com', 'http://10.0.0.22:8787', 'http://localhost.attacker.example',
    'https://user:secret@relay.example.com', 'https://relay.example.com?key=secret',
    'https://relay.example.com#token', 'javascript:alert(1)', 'file:///etc/passwd']) {
    assert.throws(() => validURL(url), Error, url);
  }
});
