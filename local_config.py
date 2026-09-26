"""Load simple local .env settings without adding a runtime dependency."""
import os
from pathlib import Path
import re


def load_env(path):
    """Load KEY=value lines; inherited environment variables take precedence.

    Supports comments, optional export prefixes, and single/double quoted values.
    Values are literal: no shell execution, interpolation, or backslash escaping.
    """
    path = Path(path)
    try:
        content = path.read_text(encoding='utf-8-sig')
    except FileNotFoundError:
        return
    values = {}
    for number, raw in enumerate(content.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        error = f'Invalid .env setting on line {number}; use KEY=value on one line.'
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ValueError(error)
        if value.startswith(('"', "'")):
            end = value.find(value[0], 1)
            if end < 0 or (value[end + 1:].strip() and not value[end + 1:].strip().startswith('#')):
                raise ValueError(error)
            value = value[1:end]
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
        if '\x00' in value:
            raise ValueError(error)
        values[key] = value
    # Validate the whole file first, avoiding partially applied configuration.
    for key, value in values.items():
        os.environ.setdefault(key, value)
