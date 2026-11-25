const test = require('node:test');
const assert = require('node:assert/strict');
const {create, voicePreference} = require('../web/js/read-aloud.js');

const setup = () => {
  const devices = [];
  const player = create(() => {
    const audio = {
      plays: 0, pauses: 0, resets: 0,
      play() { this.plays++; return Promise.resolve(); },
      pause() { this.pauses++; },
      removeAttribute(name) { delete this[name]; },
      load() { this.resets++; }
    };
    devices.push(audio);
    return audio;
  }, () => {});
  return {devices, player};
};

test('starts on demand and pauses and resumes the same audio', () => {
  const {devices, player} = setup();
  assert.equal(devices.length, 0);
  player.toggle('first');
  const [audio] = devices;
  assert.equal(player.status('first'), 'loading');
  audio.onplaying();
  player.toggle('first');
  assert.equal(player.status('first'), 'paused');
  assert.equal(audio.pauses, 1);
  player.toggle('first');
  assert.equal(devices.length, 1);
  assert.equal(audio.plays, 2);
  audio.onplaying();
  audio.onended();
  assert.equal(player.status('first'), 'idle');
  assert.equal(audio.src, undefined);
});

test('switching and stopping release the old audio, and playback errors permit retry', () => {
  const {devices, player} = setup();
  player.toggle('first');
  const lateFailure = devices[0].onerror;
  player.toggle('second');
  assert.equal(devices[0].src, undefined);
  lateFailure();
  assert.equal(player.status('second'), 'loading');
  devices[1].onerror();
  assert.equal(player.status('second'), 'error');
  player.toggle('second');
  assert.equal(devices.length, 3);
  player.stop();
  assert.equal(devices[2].resets, 1);
  assert.equal(player.status('second'), 'idle');
});

test('voice choice persists for this browser and can return to the table default', () => {
  const saved = new Map();
  const storage = {getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value),
    removeItem: key => saved.delete(key)};
  const endpoint = '/api/saves/save/read-aloud/7?playerId=player';
  const preference = voicePreference(storage);
  assert.equal(preference.url(endpoint), endpoint);
  preference.set('george');
  const reopened = voicePreference(storage);
  assert.equal(reopened.get(), 'george');
  assert.equal(reopened.url(endpoint), endpoint + '&voice=george');
  reopened.set('');
  assert.equal(voicePreference(storage).url(endpoint), endpoint);
});
