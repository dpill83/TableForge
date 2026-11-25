"""Optional CPU speech service. Run in a separate venv on the TableForge host."""
import argparse
from array import array
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import threading
import time

from read_aloud import MAX_AUDIO, MAX_TEXT, send_audio

MAX_CACHED_MESSAGES = 8
MAX_CACHED_AUDIO = 3 * 1024 * 1024


def segments(text):
    """Start with one short phrase, then grow the buffer as playback runs."""
    current = ''
    limit = 90
    first = True
    for sentence in re.split(r'(?<=[.!?…])\s+|(?<=[.!?…]["”’])\s+|\n+', text):
        if not any(character.isalnum() for character in sentence):
            continue
        for piece in textwrap.wrap(sentence, width=limit, break_on_hyphens=False):
            if first:
                first = False
                yield piece
                limit = 105
                continue
            if current and len(current) + len(piece) + 1 > limit:
                yield current
                current = ''
                limit = 220
            current = f'{current} {piece}'.strip()
    if current:
        yield current


class Kokoro:
    def __init__(self, model_dir, speaker, threads):
        import sherpa_onnx

        model = model_dir / 'model.onnx'
        if not model.is_file():
            model = model_dir / 'model.int8.onnx'
        config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(model), voices=str(model_dir / 'voices.bin'),
                tokens=str(model_dir / 'tokens.txt'), data_dir=str(model_dir / 'espeak-ng-data'),
                lexicon=str(model_dir / 'lexicon-us-en.txt')),
            num_threads=threads, provider='cpu'))
        if not config.validate():
            raise ValueError('Check the extracted Kokoro v1.0 model files.')
        self.tts = sherpa_onnx.OfflineTts(config)
        self.speaker = speaker
        if not 0 <= speaker < self.tts.num_speakers:
            raise ValueError('Kokoro speaker ID is out of range.')

    def encode(self, text):
        audio = self.tts.generate(text, sid=self.speaker, speed=1.0)
        if not audio.samples:
            raise ValueError('Kokoro returned no speech.')
        samples = array('f', audio.samples)
        if sys.byteorder != 'little':
            samples.byteswap()
        # Omit per-segment metadata so concatenated frames form one MP3 stream.
        return subprocess.run(
            ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'f32le', '-ar', str(audio.sample_rate),
             '-ac', '1', '-i', 'pipe:0', '-codec:a', 'libmp3lame', '-b:a', '128k',
             '-write_xing', '0', '-id3v2_version', '0', '-f', 'mp3', 'pipe:1'],
            input=samples.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=True, timeout=8).stdout


class SpeechServer(ThreadingHTTPServer):
    def __init__(self, port, engine):
        super().__init__(('127.0.0.1', port), SpeechHandler)
        self.engine = engine
        self.generate_lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(3)
        self.cache = OrderedDict()
        self.cache_lock = threading.Lock()

    def cached(self, text):
        with self.cache_lock:
            audio = self.cache.get(text)
            if audio is not None:
                self.cache.move_to_end(text)
            return audio

    def remember(self, text, audio):
        with self.cache_lock:
            self.cache[text] = audio
            if len(self.cache) > MAX_CACHED_MESSAGES:
                self.cache.popitem(last=False)


class SpeechHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/speech' or self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            return self.send_error(404)
        if self.headers.get_content_type() != 'application/json':
            return self.send_error(415)
        self.connection.settimeout(5)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_TEXT * 12 + 256:
                raise ValueError
            text = json.loads(self.rfile.read(size))['text']
            if not isinstance(text, str) or len(text) > MAX_TEXT or not any(c.isalnum() for c in text):
                raise ValueError
        except (KeyError, OSError, TypeError, ValueError):
            return self.send_error(400)
        cached = self.server.cached(text)
        if cached is not None:
            return self.send_cached(cached)
        if not self.server.slots.acquire(blocking=False):
            return self.send_error(503)
        try:
            if not self.server.generate_lock.acquire(timeout=8):
                return self.send_error(503)
            try:
                cached = self.server.cached(text)
                if cached is not None:
                    return self.send_cached(cached)
                self.synthesize(text)
            finally:
                self.server.generate_lock.release()
        finally:
            self.server.slots.release()

    def send_cached(self, audio):
        try:
            send_audio(self, (audio,), length=len(audio))
        except OSError:
            pass

    def synthesize(self, text):
        source = iter(segments(text))
        try:
            first = self.server.engine.encode(next(source))
        except (OSError, RuntimeError, StopIteration, ValueError, subprocess.SubprocessError):
            self.log_error('Kokoro could not start speech synthesis')
            return self.send_error(503)
        retained = bytearray()
        total = 0
        deadline = time.monotonic() + 180

        def stream():
            nonlocal total
            chunk = first
            while True:
                total += len(chunk)
                if not chunk or total > MAX_AUDIO:
                    raise ValueError('Invalid Kokoro audio size')
                if total <= MAX_CACHED_AUDIO:
                    retained.extend(chunk)
                yield chunk
                segment = next(source, None)
                if segment is None:
                    return
                if time.monotonic() >= deadline:
                    raise ValueError('Kokoro generation timed out')
                chunk = self.server.engine.encode(segment)

        try:
            send_audio(self, stream())
        except OSError:
            return  # Browser released playback.
        except (RuntimeError, ValueError, subprocess.SubprocessError):
            self.log_error('Kokoro speech stream ended early')
            return
        if total <= MAX_CACHED_AUDIO:
            self.server.remember(text, bytes(retained))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--speaker', type=int, default=3, help='Kokoro v1.0 speaker ID (default af_heart)')
    parser.add_argument('--threads', type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    with SpeechServer(args.port, Kokoro(args.model_dir, args.speaker, args.threads)) as server:
        print(f'Kokoro speech listening on 127.0.0.1:{server.server_port}', flush=True)
        server.serve_forever()
