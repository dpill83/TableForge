#!/usr/bin/env bash
# A fresh registration token is pasted into this terminal, never stored in Git.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run with sudo.' >&2; exit 1; }
cd /opt/tableforge-runner
chmod 0700 /opt/tableforge-runner
test -f config.sh
test ! -e .runner || { echo 'Runner already registered; inspect existing configuration.' >&2; exit 1; }
read -rsp 'Paste the GitHub repository runner registration token: ' runner_token
printf '\n'
# Some Windows clipboard pastes retain a carriage return. Never log the token.
runner_token=${runner_token//$'\r'/}
trap 'unset runner_token' EXIT
test -n "$runner_token"
if [[ "$runner_token" =~ [[:space:]] ]]; then
  echo 'Paste only the value after --token, without the surrounding command.' >&2
  exit 1
fi
case "$runner_token" in
  ghp_*|github_pat_*|gho_*|ghu_*|ghs_*)
    echo 'This is an API/OAuth token. Use the registration token from this repository: https://github.com/dpill83/TableForge/settings/actions/runners/new' >&2
    exit 1
    ;;
esac
runuser -u tableforge-deploy -- ./config.sh --unattended \
  --url https://github.com/dpill83/TableForge \
  --token "$runner_token" \
  --name kilo-tableforge-production \
  --no-default-labels --labels kilo-tableforge-production --work _work
unset runner_token
./svc.sh install tableforge-deploy
./svc.sh start
./svc.sh status
