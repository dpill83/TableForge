"""Read saved public narration through a loopback speech service."""
import http.client
import json
import os
import re

from narration_stream import contains_control, preview_text

MAX_TEXT = 24_000
MAX_AUDIO = 12 * 1024 * 1024
CHUNK_SIZE = 8192
VOICES = {'heart': (3, 'Heart'), 'daniel': (24, 'Daniel'),
          'george': (26, 'George'), 'fable': (25, 'Fable')}


def port():
    value = os.environ.get('TABLEFORGE_KOKORO_PORT', '')
    return int(value) if re.fullmatch(r'[0-9]{1,5}', value) and 0 < int(value) <= 65535 else None


def spoken_text(body):
    text = body.replace('\r\n', '\n').replace('\r', '\n')
    # Older buffered saves may still contain control metadata. Retain public
    # prose on both sides of a complete marker and drop any unfinished tail.
    text = re.sub(r'^[ \t]*(\x60{3,}|~{3,})[ \t]*tableforge[^\n]*\n.*?(?:^\1[ \t]*$|\Z)',
                  '', text, flags=re.I | re.M | re.S)
    text = re.sub(r'\[\[\s*tableforge[^\]\n]*\]\]|\[\s*(?:opening|location|chapter)\s*:[^\]\n]*\]',
                  '', text, flags=re.I)
    if contains_control(text):
        text = preview_text(text)
    text = re.sub(r'!?\[([^\]\n]+)\]\((?:https?://|mailto:)[^\s)]+\)', r'\1', text, flags=re.I)
    text = re.sub(r'^[ \t]*(?:#{1,6}[ \t]+|>[ \t]?|[-*+][ \t]+|\d+[.)][ \t]+)',
                  '', text, flags=re.M)
    text = re.sub(r'^[ \t]*(?:[~\x60]{3,}.*|[|:\- \t]+)$', '', text, flags=re.M)
    text = re.sub(r'(?<!\\)([*_~]{1,2}|\x60)(?=\S)(.+?)(?<=\S)\1', r'\2', text)
    text = re.sub(r'\\([\\\x60*_{}\[\]()#+.!>~|\-])', r'\1', text)
    return re.sub(r'[ \t]*\|[ \t]*', ', ', text).strip()


def available_voices():
    service_port = port()
    if service_port is None:
        return []
    conn = http.client.HTTPConnection('127.0.0.1', service_port, timeout=1)
    try:
        conn.request('GET', '/voices')
        with conn.getresponse() as response:
            if response.status != 200:
                return []
            supported = json.loads(response.read(512))
            if not isinstance(supported, list):
                return []
            return [{'id': voice, 'label': label} for voice, (_, label) in VOICES.items()
                    if voice in supported]
    except (OSError, http.client.HTTPException, ValueError):
        return []
    finally:
        conn.close()


def connect(service_port, text, voice=None):
    conn = http.client.HTTPConnection('127.0.0.1', service_port, timeout=15)
    try:
        path = '/speech' if voice is None else '/speech/' + voice
        conn.request('POST', path, json.dumps({'text': text}).encode(),
                     {'Content-Type': 'application/json', 'Connection': 'close'})
        return conn, conn.getresponse()
    except BaseException:
        conn.close()
        raise


def audio_chunks(response):
    received = 0
    while chunk := response.read1(CHUNK_SIZE):
        received += len(chunk)
        if received > MAX_AUDIO:
            raise ValueError('Audio exceeded the size limit')
        yield chunk
    if response.length not in (None, 0):
        raise http.client.IncompleteRead(b'')


def send_audio(handler, chunks, *, length=None):
    """Send audio with an explicit terminator only after successful synthesis."""
    previous_timeout = handler.connection.gettimeout()
    handler.connection.settimeout(10)
    handler.protocol_version = 'HTTP/1.1'
    handler.close_connection = True
    try:
        handler.send_response(200)
        handler.send_header('Content-Type', 'audio/mpeg')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Connection', 'close')
        if length is None:
            handler.send_header('Transfer-Encoding', 'chunked')
        else:
            handler.send_header('Content-Length', str(length))
        handler.end_headers()
        for chunk in chunks:
            if length is None:
                handler.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
            else:
                handler.wfile.write(chunk)
            handler.wfile.flush()
        if length is None:
            handler.wfile.write(b'0\r\n\r\n')
    finally:
        handler.connection.settimeout(previous_timeout)
