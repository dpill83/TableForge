#!/usr/bin/env bash
# Run this audited file with sudo from the private KILO staging directory.
set -euo pipefail
umask 027
test "$(id -u)" = 0 || { echo 'Run with sudo.' >&2; exit 1; }
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test "$(hostname)" = kilo || { echo 'This setup is scoped to KILO.' >&2; exit 1; }
for path in /opt/tableforge /opt/tableforge-runner /var/lib/tableforge /var/lib/tableforge-deploy /etc/tableforge /etc/systemd/system/tableforge.service /etc/systemd/system/tableforge-firewall.service /etc/sudoers.d/tableforge-deploy /usr/local/libexec/tableforge; do
  test ! -e "$path" || { echo "Existing path: $path. Inspect before resuming; nothing will be overwritten." >&2; exit 1; }
done
for account in tableforge tableforge-deploy; do
  if getent passwd "$account" >/dev/null; then
    echo "Account already exists: $account. Inspect before resuming." >&2; exit 1
  fi
done
python3 -c 'import ensurepip, sqlite3, venv'
command -v git >/dev/null
command -v curl >/dev/null
test -x /usr/sbin/nft
if /usr/sbin/nft list table inet tableforge >/dev/null 2>&1; then
  echo 'Existing TableForge nftables table: inspect before changing it.' >&2; exit 1
fi
# Host-specific networking stays in the private installation environment.
: "${TABLEFORGE_LAN_INTERFACE:?Set the inspected LAN interface}"
: "${TABLEFORGE_LAN_ADDRESS:?Set the reserved LAN IPv4 address}"
: "${TABLEFORGE_LAN_SUBNET:?Set the permitted LAN IPv4 subnet}"
rendered_firewall=$(mktemp)
trap 'rm -f -- "$rendered_firewall"' EXIT
python3 - "$bundle/firewall.nft" "$rendered_firewall" "$TABLEFORGE_LAN_INTERFACE" "$TABLEFORGE_LAN_ADDRESS" "$TABLEFORGE_LAN_SUBNET" <<'PY'
import ipaddress, pathlib, re, subprocess, sys
source, output, interface, address, subnet = sys.argv[1:]
assert re.fullmatch(r'[A-Za-z0-9_.:-]+', interface), 'Invalid interface'
address = ipaddress.IPv4Address(address)
subnet = ipaddress.IPv4Network(subnet, strict=True)
assert address in subnet, 'LAN address is outside the allowed subnet'
actual = subprocess.check_output(['ip', '-o', '-4', 'addr', 'show', 'dev', interface], text=True)
assert any(ipaddress.IPv4Interface(value).ip == address for value in re.findall(r'inet ([0-9./]+)', actual)), 'LAN address does not match the inspected interface'
text = pathlib.Path(source).read_text()
for marker, value in {'@LAN_INTERFACE@': interface, '@LAN_ADDRESS@': str(address), '@LAN_SUBNET@': str(subnet)}.items():
    text = text.replace(marker, value)
pathlib.Path(output).write_text(text)
PY
/usr/sbin/nft --check -f "$rendered_firewall"
if ss -ltnH 'sport = :8765' | grep -q .; then echo 'Port 8765 is occupied.' >&2; exit 1; fi
visudo -cf "$bundle/tableforge-deploy.sudoers"
useradd --system --user-group --home-dir /var/lib/tableforge --shell /usr/sbin/nologin tableforge
useradd --system --user-group --home-dir /var/lib/tableforge-deploy --shell /usr/sbin/nologin tableforge-deploy
install -d -o tableforge -g tableforge -m 0700 /var/lib/tableforge
install -d -o tableforge-deploy -g tableforge-deploy -m 0700 /var/lib/tableforge-deploy /opt/tableforge-runner
install -d -o tableforge-deploy -g tableforge -m 2750 /opt/tableforge /opt/tableforge/venvs
runuser -u tableforge-deploy -- sh -c 'umask 027; git clone --branch main --single-branch https://github.com/dpill83/TableForge.git /opt/tableforge/repo'
commit=$(runuser -u tableforge-deploy -- git -C /opt/tableforge/repo rev-parse HEAD)
runuser -u tableforge-deploy -- sh -c 'umask 027; python3 -m venv "/opt/tableforge/venvs/$1"; ln -s "/opt/tableforge/venvs/$1" /opt/tableforge/venv' sh "$commit"
test ! -e /opt/tableforge/repo/data
test ! -e /opt/tableforge/repo/.env
test -z "$(runuser -u tableforge-deploy -- git -C /opt/tableforge/repo ls-files data .env)"
# No Python dependency manifest or third-party imports exist in inspected main.
if find /opt/tableforge/repo -maxdepth 1 \( -name 'requirements*.txt' -o -name pyproject.toml -o -name setup.py \) | grep -q .; then
  echo 'main now has dependencies: inspect installation method before proceeding.' >&2; exit 1
fi
runuser -u tableforge-deploy -- sh -c 'cd /opt/tableforge/repo; TABLEFORGE_DATA=/var/lib/tableforge-deploy/test-data TABLEFORGE_OPENAI_API_KEY= TABLEFORGE_ROUTER_URL= /opt/tableforge/venv/bin/python -B -m unittest discover -s tests -q' >"$bundle/production-python-tests.log" 2>&1
if command -v node >/dev/null; then
  runuser -u tableforge-deploy -- sh -c 'cd /opt/tableforge/repo; for file in tests/test_*.cjs; do node --test "$file" || exit; done' >"$bundle/production-js-tests.log" 2>&1
fi
runuser -u tableforge -- /opt/tableforge/venv/bin/python -B -c 'import sqlite3, pathlib; assert pathlib.Path("/opt/tableforge/repo/server.py").is_file()'
install -d -o root -g tableforge -m 0750 /etc/tableforge
install -o root -g tableforge -m 0640 "$bundle/tableforge.env.example" /etc/tableforge/tableforge.env
install -o root -g root -m 0644 "$rendered_firewall" /etc/tableforge/firewall.nft
install -d -o root -g root -m 0755 /usr/local/libexec/tableforge
install -o root -g root -m 0755 "$bundle/deploy.py" /usr/local/libexec/tableforge/deploy.py
install -o root -g root -m 0755 "$bundle/snapshot.py" /usr/local/libexec/tableforge/snapshot.py
install -o root -g root -m 0755 "$bundle/verify.sh" /usr/local/libexec/tableforge/verify.sh
install -o root -g root -m 0755 "$bundle/firewall.sh" /usr/local/libexec/tableforge/firewall.sh
install -o root -g root -m 0644 "$bundle/tableforge.service" /etc/systemd/system/tableforge.service
install -o root -g root -m 0644 "$bundle/tableforge-firewall.service" /etc/systemd/system/tableforge-firewall.service
install -o root -g root -m 0440 "$bundle/tableforge-deploy.sudoers" /etc/sudoers.d/tableforge-deploy
visudo -cf /etc/sudoers.d/tableforge-deploy
systemd-analyze verify /etc/systemd/system/tableforge.service /etc/systemd/system/tableforge-firewall.service
runuser -u tableforge-deploy -- /usr/bin/python3 - "$commit" <<'PY'
import json, sys
from pathlib import Path
commit = sys.argv[1]
Path('/var/lib/tableforge-deploy/deployment.json').write_text(json.dumps({
    'current': {'commit': commit, 'venv': '/opt/tableforge/venvs/' + commit},
    'previous': None}, indent=2) + '\n')
PY
# Scope filtering to our table/port; leave inactive UFW and unrelated rules alone.
systemctl daemon-reload
systemctl enable --now tableforge-firewall.service
systemctl enable --now tableforge.service
TABLEFORGE_LAN_URL="http://$TABLEFORGE_LAN_ADDRESS:8765" /usr/local/libexec/tableforge/verify.sh
echo "TableForge installed from main: $commit"
echo "LAN URL: http://$TABLEFORGE_LAN_ADDRESS:8765"
echo 'Provider key is unset; configure /etc/tableforge/tableforge.env for real AI.'
bash "$bundle/prepare-runner.sh"
bash "$bundle/install-cloudflared.sh"
echo 'Runner package and cloudflared are installed; registration still needs your tokens.'
