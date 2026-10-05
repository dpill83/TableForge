#!/usr/bin/python3
"""Deploy only origin/main; restore the previous code and venv on restart failure."""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

BASE = Path('/opt/tableforge')
REPO = BASE / 'repo'
STATE = Path('/var/lib/tableforge-deploy')
URL = 'https://github.com/dpill83/TableForge.git'
SHA = re.compile(r'^[0-9a-f]{40}$')


def run(*args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                          stdout=subprocess.PIPE).stdout.strip()


def git(*args):
    return run('/usr/bin/git', *args, cwd=REPO)


def safe_environment(data):
    env = os.environ.copy()
    env.update(TABLEFORGE_DATA=str(data), TABLEFORGE_OPENAI_API_KEY='',
               OPENAI_API_KEY='', TABLEFORGE_ROUTER_URL='', PYTHONDONTWRITEBYTECODE='1',
               GIT_TERMINAL_PROMPT='0')
    return env


def validate_tree(commit):
    # Refuse a future commit that could overwrite storage or load repo secrets.
    paths = git('ls-tree', '-r', '--name-only', commit).splitlines()
    if any(p == 'data' or p.startswith('data/') or p == '.env' or
           (p.startswith('.env.') and p != '.env.example') for p in paths):
        raise RuntimeError('main tracks persistent data or local config; inspect before deploying')
    for path in (REPO / 'data', REPO / '.env'):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f'Unexpected local data/config in repo: {path}')


def prepare(commit):
    venv = BASE / 'venvs' / f'{commit}-{uuid.uuid4().hex[:8]}'
    run('/usr/bin/python3', '-m', 'venv', str(venv))
    with tempfile.TemporaryDirectory(prefix='tableforge-candidate-', dir=STATE) as work:
        candidate = Path(work)
        archive = candidate / 'source.tar'
        with archive.open('wb') as out:
            subprocess.run(['/usr/bin/git', 'archive', commit], cwd=REPO,
                           stdout=out, check=True)
        run('/usr/bin/tar', '-xf', str(archive), '-C', str(candidate))
        python = str(venv / 'bin/python')
        env = safe_environment(candidate / 'test-data')
        # The inspected application is standard-library-only. Follow manifests
        # if the project later adds explicit Python dependencies.
        if (candidate / 'requirements.txt').is_file():
            run(python, '-m', 'pip', 'install', '--disable-pip-version-check',
                '-r', 'requirements.txt', cwd=candidate, env=env)
        elif (candidate / 'pyproject.toml').is_file():
            run(python, '-m', 'pip', 'install', '--disable-pip-version-check', '.',
                cwd=candidate, env=env)
        elif any(candidate.glob('requirements*.txt')) or (candidate / 'setup.py').exists():
            raise RuntimeError('New dependency layout needs inspection before deployment')
        run(python, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q',
            cwd=candidate, env=env)
        if subprocess.run(['/usr/bin/which', 'node'], stdout=subprocess.DEVNULL).returncode == 0:
            for test in sorted((candidate / 'tests').glob('test_*.cjs')):
                run('node', '--test', str(test), cwd=candidate, env=env)
    return venv


def switch_venv(path):
    path = Path(path).resolve()
    if path.parent != BASE / 'venvs' or not (path / 'bin/python').exists():
        raise RuntimeError('Invalid saved virtual environment path')
    link = BASE / f'.venv-{uuid.uuid4().hex}'
    link.symlink_to(path, target_is_directory=True)
    os.replace(link, BASE / 'venv')


def healthy():
    if run('/usr/bin/systemctl', 'is-active', 'tableforge.service') != 'active':
        raise RuntimeError('TableForge service is not active')
    for path in ('/', '/api/runtime', '/api/saves'):
        with urllib.request.urlopen(f'http://127.0.0.1:8765{path}', timeout=3) as response:
            if response.status != 200:
                raise RuntimeError(f'HTTP health check failed: {path}')
            if path.startswith('/api/'):
                json.load(response)


def restart_and_check():
    run('/usr/bin/sudo', '-n', '/usr/bin/systemctl', 'restart', 'tableforge.service')
    last_error = None
    for _ in range(30):
        try:
            healthy()
            time.sleep(3)
            healthy()
            return
        except Exception as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError(f'TableForge did not recover: {last_error}')


def write_state(current, previous):
    tmp = STATE / f'.deployment-{uuid.uuid4().hex}.json'
    tmp.write_text(json.dumps({'current': current, 'previous': previous}, indent=2) + '\n')
    os.replace(tmp, STATE / 'deployment.json')


def execute(action, expected=None):
    if action not in ('deploy', 'rollback'):
        raise RuntimeError('Usage: deploy.py deploy [main-SHA] | rollback')
    if git('remote', 'get-url', 'origin') != URL or git('branch', '--show-current') != 'main':
        raise RuntimeError('Production checkout must be main with the expected origin')
    if git('status', '--porcelain'):
        raise RuntimeError('Production checkout has local changes; refusing to overwrite them')
    if (STATE / 'pending.json').exists():
        raise RuntimeError('An interrupted deployment needs inspection: /var/lib/tableforge-deploy/pending.json')
    old = {'commit': git('rev-parse', 'HEAD'), 'venv': str((BASE / 'venv').resolve())}
    if action == 'deploy':
        git('fetch', '--prune', 'origin', '+refs/heads/main:refs/remotes/origin/main')
        target = git('rev-parse', 'origin/main')
        if expected is not None:
            if not SHA.fullmatch(expected):
                raise RuntimeError('Invalid GitHub event commit')
            if expected != target:
                # A queued older main event must never roll back a newer merge.
                if subprocess.run(['/usr/bin/git', 'merge-base', '--is-ancestor',
                                   expected, target], cwd=REPO).returncode != 0:
                    raise RuntimeError('Event commit is not in origin/main history')
                print(f'Queued event {expected}; deploying latest main {target}', flush=True)
        validate_tree(target)
        if target == old['commit']:
            healthy()
            print(f'Already deployed and healthy: {target}', flush=True)
            return
        new = {'commit': target, 'venv': str(prepare(target))}
    else:
        saved = json.loads((STATE / 'deployment.json').read_text())
        new = saved['previous']
        if not new or not SHA.fullmatch(new['commit']):
            raise RuntimeError('No previous successful deployment exists yet')
        target = new['commit']
        # Rollback targets must have been deployed from main by this script.
        validate_tree(target)
    print(f'{action}: {old["commit"]} -> {target}', flush=True)
    # Persist a recovery record before modifying the checkout.
    pending = STATE / 'pending.json'
    pending.write_text(json.dumps({'old': old, 'candidate': new}, indent=2) + '\n')
    try:
        git('reset', '--hard', target)
        switch_venv(new['venv'])
        restart_and_check()
        write_state(new, old)
    except Exception:
        print('Deployment failed; restoring previous code and venv. Database is retained.', flush=True)
        git('reset', '--hard', old['commit'])
        switch_venv(old['venv'])
        restart_and_check()
        pending.unlink()
        raise
    pending.unlink()
    print(f'Healthy deployment: {target}', flush=True)


def main():
    os.umask(0o027)  # app user has read/execute access through tableforge group
    if len(sys.argv) not in (2, 3):
        raise SystemExit('Usage: deploy.py deploy [main-SHA] | rollback')
    with (STATE / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        execute(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'FAILED: {error}', file=sys.stderr, flush=True)
        raise SystemExit(1)
