#!/usr/bin/env bash
# Root-only, explicit deployment acceptance tests. No game data is modified.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run with sudo.' >&2; exit 1; }
wait_for_http() {
  for attempt in $(seq 1 30); do
    if systemctl is-active --quiet tableforge.service && curl --fail --silent --max-time 3 http://127.0.0.1:8765/api/saves >/dev/null; then return; fi
    sleep 1
  done
  journalctl -u tableforge.service -n 30 --no-pager >&2
  return 1
}
systemctl restart tableforge.service
wait_for_http
before=$(systemctl show tableforge.service -p MainPID --value)
restarts=$(systemctl show tableforge.service -p NRestarts --value)
# Simulate a process crash; SIGKILL cannot be mistaken for a clean shutdown.
systemctl kill --signal=SIGKILL --kill-whom=main tableforge.service
sleep 4
wait_for_http
after=$(systemctl show tableforge.service -p MainPID --value)
test "$before" != "$after"
test "$(systemctl show tableforge.service -p NRestarts --value)" -gt "$restarts"
test "$(systemctl is-enabled tableforge.service)" = enabled
curl --fail --silent --max-time 5 http://127.0.0.1:8765/ >/dev/null
if test -n "${TABLEFORGE_LAN_URL:-}"; then
  curl --fail --silent --max-time 5 "$TABLEFORGE_LAN_URL/" >/dev/null
fi
systemctl status tableforge.service --no-pager
journalctl -u tableforge.service -n 12 --no-pager
ss -ltnp 'sport = :8765'
test "$(systemctl is-enabled tableforge-firewall.service)" = enabled
systemctl is-active --quiet tableforge-firewall.service
/usr/sbin/nft list table inet tableforge
runuser -u tableforge -- env TABLEFORGE_DATA=/var/lib/tableforge /opt/tableforge/venv/bin/python -B - <<'PY'
import sqlite3
from pathlib import Path
path = Path('/var/lib/tableforge/tableforge.sqlite3')
with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
assert not Path('/opt/tableforge/repo/data').exists()
assert not Path('/opt/tableforge/repo/.env').exists()
print('Persistent storage is outside Git; database integrity: ok')
PY
echo 'Restart, failure recovery, boot enablement, HTTP and storage checks passed.'
echo 'Test LAN HTTP from a separate home-network device as well.'
