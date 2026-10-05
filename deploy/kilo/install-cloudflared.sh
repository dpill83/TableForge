#!/usr/bin/env bash
# Supported Cloudflare Debian-family package repository; no tunnel token needed yet.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run with sudo.' >&2; exit 1; }
if command -v cloudflared >/dev/null; then cloudflared --version; exit 0; fi
for path in /etc/apt/sources.list.d/cloudflared.list /usr/share/keyrings/cloudflare-main.gpg; do
  test ! -e "$path" || { echo "Inspect existing $path before continuing." >&2; exit 1; }
done
temporary=$(mktemp)
trap 'rm -f -- "$temporary"' EXIT
curl --fail --silent --show-error --location https://pkg.cloudflare.com/cloudflare-main.gpg -o "$temporary"
install -m 0644 "$temporary" /usr/share/keyrings/cloudflare-main.gpg
printf '%s\n' 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' >/etc/apt/sources.list.d/cloudflared.list
chmod 0644 /etc/apt/sources.list.d/cloudflared.list
# Update this package source only; do not upgrade unrelated KILO software.
apt-get update -o Dir::Etc::sourcelist=sources.list.d/cloudflared.list -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0
env NEEDRESTART_MODE=l apt-get install -y cloudflared
cloudflared --version
echo 'Installed; tunnel registration/service installation needs your Cloudflare token.'
