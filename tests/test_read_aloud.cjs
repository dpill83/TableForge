const test = require('node:test');
const assert = require('node:assert/strict');
const {create} = require('../web/js/read-aloud.js');

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
