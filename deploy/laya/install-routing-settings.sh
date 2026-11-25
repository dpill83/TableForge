#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID != 0 ]]; then
  echo 'Run this installer with sudo on Kilo.' >&2
  exit 1
fi

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
router=/opt/laya
data=/var/lib/laya-router
database=$data/ai-routing.sqlite3
router_user=$(systemctl show laya-router.service -p User --value)
if [[ -z $router_user || ! -x $router/.venv/bin/python || ! -f $router/router_service.py ]]; then
  echo 'The installed Kilo Laya router could not be found.' >&2
  exit 1
fi
router_group=$(systemctl show laya-router.service -p Group --value)
router_group=${router_group:-$(id -gn "$router_user")}

install -d -m 2750 -o tableforge -g "$router_group" "$data"
if [[ -e $database ]]; then
  runuser -u "$router_user" -- test -r "$database"
  runuser -u tableforge -- test -w "$database"
fi

backup=$(mktemp -d /var/backups/laya-routing.XXXXXX)
files=(router_service.py router_policy.py routing_settings.py)
for file in "${files[@]}"; do
  if [[ -e $router/$file ]]; then
    cp -p -- "$router/$file" "$backup/$file"
  fi
done
echo "Laya source backup: $backup"

rollback() {
  result=$?
  trap - EXIT
  if (( result != 0 )); then
    echo 'Laya settings installation failed. Restoring the previous router.' >&2
    for file in "${files[@]}"; do
      if [[ -e $backup/$file ]]; then
        cp -p -- "$backup/$file" "$router/$file"
      else
        rm -f -- "$router/$file"
      fi
    done
    systemctl restart laya-router.service
  fi
  exit "$result"
}
trap rollback EXIT

install -m 0644 "$repo/deploy/laya/router_service.py" "$repo/deploy/laya/router_policy.py" "$router/"
install -m 0644 "$repo/routing_settings.py" "$router/"
(
  cd -- "$router"
  runuser -u "$router_user" -- .venv/bin/python -B -c '
import router_service, routing_settings
assert router_service.app.version == "0.3.0"
routing_settings.load(routing_settings.laya_data_path())
'
)
systemctl restart laya-router.service

check_router() (
  cd -- "$repo"
  runuser -u tableforge -- /opt/tableforge/venv/bin/python -B -c '
from configure_ai_routing import laya_base_models, load_env
load_env("/etc/tableforge/tableforge.env")
laya_base_models()
'
)
for attempt in {1..10}; do
  if check_router 2>/dev/null; then
    if [[ ! -e $database ]]; then
      install -m 0640 -o tableforge -g "$router_group" /dev/null "$database"
    fi
    echo 'Laya service defaults are ready in the TableForge routing editor.'
    exit 0
  fi
  sleep 1
done
echo 'The updated Laya router did not expose its routing defaults.' >&2
exit 1
