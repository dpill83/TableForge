# KILO production deployment

This deployment is scoped to `dpill83/TableForge`, GitHub branch `main`, and
the production host KILO. LAN addresses and interfaces are supplied privately
at installation time. It does not change router configuration.

## Application and storage

`python3 server.py` starts a standard-library `ThreadingHTTPServer` on
`127.0.0.1:8765` by default. `--host` and `--port` select the listener.
The inspected main commit is `3d28cb3ebefd4d1823a2f554a8248923d9cef3d9`.
It requires Python 3.10+, has no Python dependency manifest, and uses no
third-party Python packages. OpenAI requests use the standard library HTTP client.

`TABLEFORGE_DATA` changes all persistent application storage. The SQLite file
contains saves, per-save players, messages, portraits, attachments, generated
images, prompt snapshots, request metadata and usage. Cartridge ZIPs live in
`cartridges/`; database-only backups live in `backups/`. Browser drafts/preferences
are browser-local. Existing Windows storage is a separate fallback.
Keep the Windows database, cartridges, logs, diagnostics and `.env` as fallback.
No Windows files are copied, moved, deleted, or changed by this setup.

Production paths:

| Purpose | Path | Owner / access |
| --- | --- | --- |
| Main-only Git checkout | `/opt/tableforge/repo` | `tableforge-deploy:tableforge`, runtime read-only |
| Current Python venv | `/opt/tableforge/venv` | symlink to a retained venv |
| Per-deployment venvs | `/opt/tableforge/venvs/` | deploy writes, runtime reads |
| SQLite, cartridges, backups | `/var/lib/tableforge/` | `tableforge`, mode 0700 |
| Environment and provider credentials | `/etc/tableforge/tableforge.env` | root:tableforge, mode 0640 |
| Commit/venv history, lock, recovery record | `/var/lib/tableforge-deploy/` | deployment user, mode 0700 |
| Fixed deployment/snapshot/verification scripts | `/usr/local/libexec/tableforge/` | root-owned |
| Application unit | `/etc/systemd/system/tableforge.service` | root-owned |
| Port-only firewall | `/etc/tableforge/firewall.nft`, `/etc/systemd/system/tableforge-firewall.service` | own nftables table, root-owned |
| Runner | `/opt/tableforge-runner/` | deployment user, mode 0700 |
| Narrow runner sudo grant | `/etc/sudoers.d/tableforge-deploy` | restart only |
| Tunnel token | `/etc/cloudflared/tableforge.token` | root:tableforge-tunnel, mode 0640 |
| Tunnel unit | `/etc/systemd/system/cloudflared.service` | non-root tunnel process |
| Operational logs | journald | `tableforge.service` / runner / tunnel units |

`.gitignore` excludes `/data/`, `.env`, `.env.*`, and Python caches.
Ignored files can still be replaced if a future commit tracks the same path.
Production data/config/venvs are therefore outside the checkout; deployments
reject both tracked data/config paths and local `data/` or `.env` in the repo.
No `git clean` is used. Local production edits cause deployment to abort.

## Initial privileged installation

Copy these templates to a private staging directory on KILO. KILO requires
interactive sudo; run this in your own terminal, without sharing the password.
Set the three variables to the LAN interface, reserved IPv4 address, and
allowed IPv4 subnet that you inspected on the server:

```bash
ssh kilo
sudo env TABLEFORGE_LAN_INTERFACE="$LAN_INTERFACE" \
  TABLEFORGE_LAN_ADDRESS="$LAN_ADDRESS" TABLEFORGE_LAN_SUBNET="$LAN_SUBNET" \
  bash ./install.sh
```

The script refuses existing production paths/accounts rather than overwrite
them. If an installation stops partway through, inspect the error and created
paths before resuming; do not delete a data directory to force a rerun.
It clones current GitHub main, creates the venv, tests that main, creates a fresh
database through normal application startup, and enables `tableforge.service`.
It uses a dedicated non-root application user and logs to journald.

The service binds IPv4 `0.0.0.0:8765` to support both LAN and local tunnel access.
UFW's unit is active but `/etc/ufw/ufw.conf` has `ENABLED=no`; its filtering is
inactive. A dedicated `tableforge-firewall.service` loads only an `inet tableforge`
nftables table: allow TCP 8765 on loopback, allow it from the configured LAN
subnet on the inspected interface to the reserved address, then drop other
inbound TCP 8765. The installer validates and renders `firewall.nft`; do not
load its unrendered placeholders directly. All other traffic
continues through KILO's existing firewall/VPN rules. The application requires
this firewall service, including at boot. The rules replace only this table in
one transaction and never flush the overall ruleset. UFW remains inactive.
It adds no WAN, SSH, IPv6 listener, router forwarding or unrelated firewall rules. Cloudflare metrics
bind only to `127.0.0.1:20241` when the tunnel is configured.

After setup, test `http://<reserved-LAN-address>:8765` from a different LAN device.
Firewall rules protect the origin; no external scan or router audit is performed.
Reserve KILO's existing IP in your router if it is not already stable.

Real narration/image generation needs provider settings in the separate file:

```bash
sudoedit /etc/tableforge/tableforge.env
sudo systemctl restart tableforge.service
```

The empty key intentionally starts the mock AI-DM. Copy any desired API key and
model/router settings yourself from Windows `.env`; do not copy its data path.
No provider credentials are written to the repository or workflow.

## Register GitHub runner

The initial installer also extracts the runner and installs cloudflared, without
registering either service. If either package step fails, rerun that individual
step after inspecting its error; do not rerun the fresh-only application installer.

Stage the verified Linux x64 runner archive (2.337.0) in `../downloads/`
relative to this bundle. Official release asset SHA-256:
`70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613`.

If the initial installer stopped before extracting the runner:

```bash
sudo bash ./prepare-runner.sh
```

Obtain a fresh one-hour repository registration token from:
[TableForge → Settings → Actions → Runners → New self-hosted runner](https://github.com/dpill83/TableForge/settings/actions/runners/new).
Choose Linux / x64 and copy the token from the Configure command. Then:

```bash
sudo bash ./register-runner.sh
```

Paste the token at the hidden prompt. The script registers
`kilo-tableforge-production` with only the matching custom label, installs the
official runner systemd service as `tableforge-deploy`, and starts it.
See [GitHub runner registration](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)
and [service instructions](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application?platform=linux).

Commit the accompanying repository changes on a deployment feature branch, push the
branch, and merge its PR into `main` to activate `.github/workflows/deploy-kilo.yml`.
No commit/push/PR is performed by this setup. Do not switch the production clone
to that branch. The workflow has only main pushes and manual dispatch; manual
dispatch also refuses any other branch. It has read-only GitHub permissions,
one queued deployment at a time, and no PR-triggered job.

This is a public repository. Keep PR/untrusted workflows on GitHub-hosted runners,
never add pull_request or pull_request_target jobs using this production label,
and require review of main/workflow changes. Custom labels prevent accidental
generic runner selection; they are not an authorization boundary. Anyone who
can run arbitrary code on this runner effectively has deployment authority.
The runner's only passwordless root permission is
`/usr/bin/systemctl restart tableforge.service`; it cannot edit service/config or
run root shells. The app process cannot write the code checkout or venv.

## Cloudflare

cloudflared is installed by the initial installer from the
[supported Cloudflare Debian-family package repository](https://pkg.cloudflare.com/).
If that package step did not complete:

```bash
sudo bash ./install-cloudflared.sh
```

Choose your hostname/domain; none is inferred. In the Cloudflare dashboard,
create a remotely managed cloudflared tunnel for KILO and obtain its connector
token. Before publishing the route, create a Cloudflare Access application for
the chosen hostname and restrict it to your trusted players. TableForge itself
has no login and Pilot Mode is not authentication.

Configure a Published application route for that chosen hostname with origin
`http://127.0.0.1:8765`. Follow
[Cloudflare's dashboard tunnel instructions](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).
Then run:

```bash
sudo bash ./register-cloudflared.sh
```

Paste the connector token at the hidden prompt. It is kept outside Git and
process arguments using Cloudflare's supported
[token-file parameter](https://developers.cloudflare.com/tunnel/reference/run-parameters/).
The `cloudflared.service` runs as `tableforge-tunnel`, starts at boot and restarts
on failure. Confirm the connector is Healthy and test the selected HTTPS URL,
including Access authentication, from outside the LAN. No origin port is opened
to the public Internet. If outbound connectivity is blocked by KILO's existing
VPN/firewall, inspect that failure before changing any unrelated network settings.

## Deployment and rollback

The installed root-owned deploy script runs as `tableforge-deploy` without
root privileges except service restart. It locks deployments, verifies the
remote/branch/clean checkout, fetches only main, and builds/tests a candidate
using a new retained venv and disposable test data. If dependency manifests
appear, it follows `requirements.txt` or `pyproject.toml`, otherwise requires
inspection of an unfamiliar dependency layout. Existing Python tests run, plus
existing JavaScript tests when Node is available.

Only after tests pass does it reset the production checkout to origin/main,
switch the venv symlink, restart and check systemd plus HTTP `/`, `/api/runtime`
and `/api/saves` twice. A queued old main event deploys the latest fetched main,
never rolls the host back to an older event SHA. Both successful commit and venv
are recorded. Restart/health failure attempts to restore the old code and venv
and still fails the Action. A timeout/interruption leaves `pending.json` for
operator inspection before a later deployment can proceed.

Before every service start, a consistent SQLite backup is created in
`/var/lib/tableforge/backups/` under a unique filename. The first fresh start has
no database to back up. Cartridges are preserved independently. Backups and venvs
are retained without automatic deletion; monitor disk use and prune deliberately
after deciding which backups to keep.

Rollback restores code and venv only; it never silently rewinds the database.
A schema-incompatible main commit may need a reviewed database restore. Before
manually restoring a backup, stop the service and preserve the current database
and cartridges. Restoring an older database can lose newer play history; inspect
and choose the backup first. Initial installation has no prior code version;
rollback becomes available after the first successful deployment to a new SHA.

If `pending.json` exists, inspect its old/candidate commits and venvs, the current
HEAD/symlink, and service logs. Recover the saved known-good code/venv as the
deployment user and restart as administrator. Clear the recovery record only
after health checks pass. No automatic database rollback is attempted.

## Operator commands (on KILO, after installation)

```bash
# Logs / service control
sudo journalctl -u tableforge.service -f
sudo systemctl restart tableforge.service
sudo systemctl stop tableforge.service
sudo systemctl start tableforge.service
systemctl status tableforge.service --no-pager
systemctl is-enabled tableforge.service

# Current deployed commit and retained versions
sudo -u tableforge-deploy git -C /opt/tableforge/repo log -1 --format='%H %s'
sudo -u tableforge-deploy cat /var/lib/tableforge-deploy/deployment.json

# Main-only manual deployment / previous successful code and venv
sudo -u tableforge-deploy /usr/local/libexec/tableforge/deploy.py deploy
sudo -u tableforge-deploy /usr/local/libexec/tableforge/deploy.py rollback

# Acceptance tests (restarts and deliberately kills the process once)
sudo /usr/local/libexec/tableforge/verify.sh

# Local / LAN / firewall verification
curl --fail http://127.0.0.1:8765/api/saves
curl --fail "http://$LAN_ADDRESS:8765/"
systemctl status tableforge-firewall.service --no-pager
sudo nft list table inet tableforge
ss -ltn 'sport = :8765'

# Optional tunnel and runner services
systemctl status cloudflared.service --no-pager
sudo journalctl -u cloudflared.service -n 30 --no-pager
systemctl list-units 'actions.runner.*' --no-pager
sudo bash -c 'cd /opt/tableforge-runner && ./svc.sh status'
```

The host reboot itself is not forced by installation. Boot readiness is checked
through systemd enablement; verify again after the next planned KILO reboot.
