"""Public code fingerprints; never include configuration or campaign data."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = '2.0.1'


def fingerprint(files):
    digest = hashlib.sha256()
    for file in sorted(files):
        digest.update(file.relative_to(ROOT).as_posix().encode('utf-8'))
        digest.update(b'\0')
        # Normalize checkout line endings so Windows and Linux IDs agree.
        digest.update(file.read_bytes().replace(b'\r\n', b'\n'))
        digest.update(b'\0')
    return digest.hexdigest()[:12]


def server_build():
    return fingerprint(list(ROOT.glob('*.py')) + list((ROOT / 'prompts').rglob('*.md')))


def ui_build():
    return fingerprint(file for file in (ROOT / 'web').rglob('*')
                       if file.is_file() and file.suffix in {'.html', '.js', '.css', '.svg'})


# Keep the running process identity stable even after files are replaced.
RUNNING_SERVER_BUILD = server_build()


def status():
    installed = server_build()
    return {'version': VERSION, 'serverBuild': RUNNING_SERVER_BUILD,
            'installedServerBuild': installed, 'uiBuild': ui_build(),
            'restartRequired': installed != RUNNING_SERVER_BUILD}
