#!/usr/bin/env bash
# Create a remotely managed tunnel/Access route in Cloudflare before running.
set -euo pipefail
umask 077
parse_tunnel_token() {
  local value=${1//$'\r'/}
  value=${value#"${value%%[![:space:]]*}"}
  value=${value%"${value##*[![:space:]]}"}
  case "$value" in
    'sudo cloudflared service install '*) value=${value#'sudo cloudflared service install '} ;;
    'cloudflared service install '*) value=${value#'cloudflared service install '} ;;
    'cloudflared.exe service install '*) value=${value#'cloudflared.exe service install '} ;;
  esac
  [[ ${#value} -ge 100 && "$value" =~ ^[A-Za-z0-9_+/-]+={0,2}$ ]] || return 1
  printf '%s' "$value"
}
test "$(id -u)" = 0 || { echo 'Run with sudo.' >&2; exit 1; }
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test -x /usr/bin/cloudflared || { echo 'Run install-cloudflared.sh first.' >&2; exit 1; }
for path in /etc/cloudflared /etc/systemd/system/cloudflared.service; do
  test ! -e "$path" || { echo "Existing $path: inspect before registration." >&2; exit 1; }
done
if getent passwd tableforge-tunnel >/dev/null; then
  echo 'tableforge-tunnel user already exists; inspect before registration.' >&2; exit 1
fi
if ss -ltnH 'sport = :20241' | grep -q .; then echo 'Metrics port 20241 is occupied.' >&2; exit 1; fi
trap 'unset tunnel_input tunnel_token' EXIT
read -rsp 'Paste the tunnel token or dashboard service-install command (hidden): ' tunnel_input
printf '\n'
tunnel_token=$(parse_tunnel_token "$tunnel_input") || {
  echo 'Paste the full tunnel connector token or the single service-install command. No changes made.' >&2
  exit 1
}
unset tunnel_input
useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin tableforge-tunnel
install -d -o root -g tableforge-tunnel -m 0750 /etc/cloudflared
printf '%s' "$tunnel_token" >/etc/cloudflared/tableforge.token
unset tunnel_token
chown root:tableforge-tunnel /etc/cloudflared/tableforge.token
chmod 0640 /etc/cloudflared/tableforge.token
install -m 0644 "$bundle/cloudflared.service" /etc/systemd/system/cloudflared.service
systemd-analyze verify /etc/systemd/system/cloudflared.service
systemctl daemon-reload
systemctl enable --now cloudflared.service
sleep 5
systemctl is-active --quiet cloudflared.service
systemctl status cloudflared.service --no-pager
journalctl -u cloudflared.service -n 15 --no-pager
echo 'Confirm connector Healthy in Cloudflare and test your selected HTTPS hostname.'
