/* One player per tab, independent of the shared table state. */
const TableForgeReadAloud = (() => {
  const icons = {
    speaker: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 9h4l5-4v14l-5-4H3zM15 9a4 4 0 0 1 0 6m2-8a7 7 0 0 1 0 10"/></svg>',
    pause: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5v14m6-14v14"/></svg>',
    play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 12 7-12 7z"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>'
  };

  const create = (makeAudio, update) => {
    let current = null;

    const release = entry => {
      const audio = entry?.audio;
      if (!audio) return;
      audio.onplaying = audio.onwaiting = audio.onended = audio.onerror = null;
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      entry.audio = null;
    };

    const stop = () => {
      const previous = current;
      current = null;
      release(previous);
      if (previous) update();
    };

    const status = url => current?.url === url ? current.status : 'idle';

    const play = entry => {
      const audio = entry.audio;
      entry.status = 'loading';
      update();
      const fail = () => {
        if (current !== entry || entry.audio !== audio) return;
        release(entry);
        entry.status = 'error';
        update();
      };
      audio.onerror = fail;
      audio.play().catch(fail);
    };

    const toggle = url => {
      if (current?.url === url && current.audio) {
        if (current.status === 'playing') {
          current.audio.pause();
          current.status = 'paused';
          update();
        } else if (current.status === 'paused') {
          play(current);
        }
        return;
      }
      stop();
      const entry = {url, audio: makeAudio(), status: 'loading'};
      current = entry;
      const audio = entry.audio;
      audio.src = url;
      audio.onplaying = () => {
        if (current !== entry || entry.status === 'paused') return;
        entry.status = 'playing';
        update();
      };
      audio.onwaiting = () => {
        if (current !== entry || entry.status === 'paused') return;
        entry.status = 'loading';
        update();
      };
      audio.onended = () => { if (current === entry) stop(); };
      play(entry);
    };

    return {toggle, stop, status};
  };

  const voicePreference = storage => {
    const key = 'tableforge-read-aloud-voice';
    let voice = '';
    try { voice = storage.getItem(key) || ''; } catch { /* Use the table default. */ }
    return {
      get: () => voice,
      set(value) {
        voice = value;
        try {
          if (voice) storage.setItem(key, voice);
          else storage.removeItem(key);
        } catch { /* Keep the choice for this tab. */ }
      },
      url: base => voice ? base + '&voice=' + encodeURIComponent(voice) : base
    };
  };

  return {icons, create, voicePreference};
})();

if (typeof module !== 'undefined') module.exports = TableForgeReadAloud;
