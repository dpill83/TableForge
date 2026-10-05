#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 0
# Replace only our own table in one nft transaction. Never flush the ruleset.
{
  if /usr/sbin/nft list table inet tableforge >/dev/null 2>&1; then
    printf '%s\n' 'delete table inet tableforge'
  fi
  cat /etc/tableforge/firewall.nft
} | /usr/sbin/nft -f -
/usr/sbin/nft list table inet tableforge
