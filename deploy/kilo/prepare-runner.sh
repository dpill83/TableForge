#!/usr/bin/env bash
# Run after install.sh. Archive was downloaded and checksum-verified in staging.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run with sudo.' >&2; exit 1; }
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
archive="$bundle/../downloads/actions-runner-linux-x64-2.337.0.tar.gz"
printf '%s  %s\n' 70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613 "$archive" | sha256sum -c -
test -d /opt/tableforge-runner
test -z "$(find /opt/tableforge-runner -mindepth 1 -maxdepth 1 -print -quit)" || { echo 'Runner directory has existing contents; inspect first.' >&2; exit 1; }
cat "$archive" | runuser -u tableforge-deploy -- tar -xzf - -C /opt/tableforge-runner
chmod 0700 /opt/tableforge-runner
# Detect missing shared libraries without installing unrelated packages blindly.
if ldd /opt/tableforge-runner/bin/Runner.Listener | grep -q 'not found'; then
  echo 'Runner native dependencies are missing; review bin/installdependencies.sh.' >&2; exit 1
fi
runuser -u tableforge-deploy -- /opt/tableforge-runner/bin/Runner.Listener --version
echo 'Runner extracted. Registration needs a fresh repository registration token.'
