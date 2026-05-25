# Deployment

How to self-host **devboard** on a single VPS (DigitalOcean, Hetzner, Selectel, etc.)
using Docker, docker-compose, and Caddy as an HTTPS reverse proxy.

> This guide assumes you are running the app for yourself or a small team on one
> host. It is **not** a Kubernetes / multi-region setup.
>
> Estimated time: 15-20 minutes on a fresh Ubuntu VPS.

Whenever you see `USER-EDIT:` in a snippet below, replace the placeholder with
your own value before running the command.

---

## 1. Prerequisites

You need:

- A VPS running **Ubuntu 22.04 LTS or newer** (24.04 also works).
- A non-root user with `sudo` rights. The rest of this guide assumes the user
  is called `devboard`. Adapt if yours is different.
- A domain name (or sub-domain) whose **A record points to the VPS public IP**.
  Example: `devboard.example.com → 203.0.113.42`. Wait until `dig +short devboard.example.com`
  returns the right IP before continuing — Caddy needs working DNS to issue a
  TLS certificate.
- TCP ports **80** and **443** open in the VPS firewall and any cloud-provider
  security group. Port `5000` does **not** need to be public — it stays bound to
  `localhost` and is only reached by Caddy.
- At least **1 GB RAM** and **5 GB free disk**. The app itself is small; the
  Docker image is around 200 MB.

If you use `ufw`:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

---

## 2. Install Docker and the compose plugin

Follow the official Docker repo instructions
(<https://docs.docker.com/engine/install/ubuntu/>). The condensed version:

```bash
# Remove any old / distro-packaged Docker
sudo apt-get remove -y docker docker-engine docker.io containerd runc || true

# Install prerequisites and Docker's GPG key
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the Docker apt repo
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

# Install Docker Engine + compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
                        docker-buildx-plugin docker-compose-plugin

# Let your user run docker without sudo (re-login after this)
sudo usermod -aG docker "$USER"
```

Verify:

```bash
docker --version
docker compose version
```

You should see Docker Engine 24.x or newer and Compose v2.x.

---

## 3. Clone the repo and configure `.env`

```bash
cd /opt
sudo mkdir -p devboard
sudo chown "$USER":"$USER" devboard
git clone https://github.com/userdevs/devboard.git devboard
cd devboard
```

> The repo URL above is the canonical one. Replace it with your fork if you
> maintain one.

Create the environment file:

```bash
cp .env.example .env
```

Open `.env` with your editor (`nano .env`) and set at minimum:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes (or `OPENAI_API_KEY`) | LLM provider credentials. Used by `llm/factory.py`. Get it from <https://console.anthropic.com/>. |
| `DEVBOARD_DASHBOARD_HOST` | recommended | Bind address inside the container. Set to `0.0.0.0` so Docker can publish the port. |
| `DEVBOARD_DASHBOARD_PORT` | optional | Defaults to `4999`. Keep it unless you have a reason to change it. |
| `DEVBOARD_TASKS_DB` | optional | Defaults to `/app/data/tasks.db` (mounted volume). |
| `DEVBOARD_DASHBOARD_LOG_LEVEL` | optional | `INFO` (default) or `DEBUG`. |

Alternative LLM providers (pick one):

- `OPENAI_API_KEY=sk-...` — use OpenAI instead of Anthropic.
- `OLLAMA_URL=http://host.docker.internal:11434` — use a local Ollama instance.

After editing, lock the file down so other users on the box cannot read your
keys:

```bash
chmod 600 .env
```

---

## 4. Bring the stack up

```bash
docker compose up -d
```

Verify it is running and healthy:

```bash
docker compose ps
```

You should see one service (typically `web`) in state `running` and health
`healthy`. The healthcheck calls `GET /healthz` inside the container every 30s
(see `Dockerfile`).

Quick smoke test from the host:

```bash
curl -fsS http://localhost:4999/healthz
# expected: {"status":"ok"} or HTTP 200
```

If the curl fails, jump to [Troubleshooting](#9-troubleshooting).

To follow logs:

```bash
docker compose logs -f
```

To stop the stack:

```bash
docker compose down
```

To pull a new version and restart:

```bash
git pull
docker compose pull        # if you use a pre-built image
docker compose up -d --build
```

---

## 5. Caddy reverse proxy (automatic HTTPS)

Caddy gives you free Let's Encrypt certificates with zero configuration. Install
it from the official apt repo:

```bash
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update
sudo apt-get install -y caddy
```

Edit the Caddyfile:

```bash
sudo nano /etc/caddy/Caddyfile
```

Replace the contents with the snippet below. **USER-EDIT:** change
`devboard.example.com` to your real domain and `you@example.com` to your real email
(Let's Encrypt uses it for expiry warnings).

```caddy
{
  email you@example.com
}

devboard.example.com {
  reverse_proxy localhost:4999

  encode zstd gzip

  # Basic security headers
  header {
    Strict-Transport-Security "max-age=31536000; includeSubDomains"
    X-Content-Type-Options "nosniff"
    Referrer-Policy "strict-origin-when-cross-origin"
  }

  log {
    output file /var/log/caddy/devboard.log {
      roll_size 10MiB
      roll_keep 5
    }
  }
}
```

Validate and reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy will obtain a certificate on first request. Open
`https://devboard.example.com/` in your browser — you should see the kanban UI
served over HTTPS.

To watch Caddy logs while debugging:

```bash
sudo journalctl -u caddy -f
```

---

## 6. systemd unit (fallback / start-on-boot)

Docker already starts on boot, and `docker compose up -d` containers come back
up automatically because they use `restart: unless-stopped`. The unit below is
a belt-and-braces fallback that runs `docker compose up` at boot and brings the
stack down cleanly on shutdown — useful on hosts where the Docker daemon's auto-
restart is unreliable (e.g. after kernel updates).

Create `/etc/systemd/system/devboard.service`:

```ini
[Unit]
Description=devboard kanban (docker compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/devboard
EnvironmentFile=/opt/devboard/.env
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=120
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now devboard.service
sudo systemctl status devboard.service
```

After a reboot the stack will come up on its own.

---

## 7. Backups

The whole state of the app lives in a single SQLite file: `data/tasks.db`
(mounted into the container at `/app/data/tasks.db`). Back it up with
`sqlite3 .dump` so you get a portable SQL text dump, not a binary snapshot that
may be mid-write.

Create `/opt/devboard/scripts/backup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/devboard
BACKUP_DIR=/opt/devboard/backups
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"
cd "$APP_DIR"

STAMP=$(date +%F-%H%M)
OUT="$BACKUP_DIR/tasks-$STAMP.sql"

# Use the sqlite3 inside the container so we don't need it on the host.
docker compose exec -T web sqlite3 /app/data/tasks.db .dump > "$OUT"

gzip -f "$OUT"

# Rotate: delete backups older than RETENTION_DAYS days.
find "$BACKUP_DIR" -name 'tasks-*.sql.gz' -mtime "+$RETENTION_DAYS" -delete

echo "backup ok: $OUT.gz"
```

Make it executable and try it once:

```bash
chmod +x /opt/devboard/scripts/backup.sh
/opt/devboard/scripts/backup.sh
ls -lh /opt/devboard/backups/
```

Schedule it daily at 03:30 via cron:

```bash
crontab -e
```

Add the line:

```cron
30 3 * * * /opt/devboard/scripts/backup.sh >> /opt/devboard/backups/backup.log 2>&1
```

> **Off-site copies:** the script above keeps backups on the same VPS. For real
> protection, also `rsync` or `rclone` the `backups/` directory to another host
> or S3-compatible storage. That is out of scope for this guide.

Restore (on a fresh host):

```bash
zcat tasks-2026-05-21-0330.sql.gz | docker compose exec -T web sqlite3 /app/data/tasks.db
```

---

## 8. Monitoring

### Container health

`docker compose ps` shows the per-service health column. The container is
healthy when `/healthz` returns HTTP 200.

### Logs

```bash
# follow live
docker compose logs -f --tail=200

# only the web service
docker compose logs -f web

# Caddy access + TLS issuance
sudo journalctl -u caddy -f
```

Both Docker and Caddy log to journald, so `journalctl --since "1 hour ago"` is
your friend.

### Healthcheck script

Create `/opt/devboard/scripts/healthcheck.sh` for an external monitor
(UptimeRobot, Healthchecks.io, or a cron that emails on failure):

```bash
#!/usr/bin/env bash
set -euo pipefail

URL=${1:-http://localhost:4999/healthz}

if curl -fsS --max-time 5 "$URL" >/dev/null; then
  echo "ok"
  exit 0
else
  echo "FAIL: $URL did not return 2xx"
  exit 1
fi
```

```bash
chmod +x /opt/devboard/scripts/healthcheck.sh
/opt/devboard/scripts/healthcheck.sh
```

For Healthchecks.io-style pings, add to cron:

```cron
* * * * * /opt/devboard/scripts/healthcheck.sh && curl -fsS --retry 3 https://hc-ping.com/USER-EDIT-uuid >/dev/null
```

### Disk usage

The SQLite DB stays small (tens of MB even after years of use), but Docker
images and old logs can pile up. Once a month:

```bash
docker system prune -af --filter "until=720h"   # remove images unused > 30d
sudo journalctl --vacuum-time=30d
```

---

## 9. Troubleshooting

### Port 5000 already in use

```
Error response from daemon: driver failed programming external connectivity
on endpoint web: ... bind: address already in use
```

Something else on the host (often a previous `python дашборд/app.py`) is on
port 5000. Find and stop it:

```bash
sudo lsof -i :5000
# or
sudo ss -ltnp | grep :5000
```

Then `kill <PID>` or change the host-side port mapping in `docker-compose.yml`.

### Caddy cannot issue a certificate

Symptoms in `journalctl -u caddy -f`:

```
challenge failed ... no such host
```

Causes and fixes:

- **DNS not propagated.** Run `dig +short devboard.example.com`. The result must
  match your VPS public IP (`curl -s ifconfig.me`). Wait up to an hour after
  changing DNS, then retry: `sudo systemctl reload caddy`.
- **Port 80 blocked.** Let's Encrypt's HTTP-01 challenge needs inbound port 80.
  Check `sudo ufw status` and the cloud provider's security group.
- **Rate-limited by Let's Encrypt.** If you reloaded Caddy many times during
  testing you may hit the staging cutoff. Use the staging issuer while
  experimenting by adding `acme_ca https://acme-staging-v02.api.letsencrypt.org/directory`
  inside the global `{ ... }` block.

### `502 Bad Gateway` from Caddy

Caddy reaches the host but the app is not answering on `localhost:4999`. Check:

```bash
docker compose ps
curl -v http://localhost:4999/healthz
```

If `docker compose ps` shows the container as `unhealthy`, look at
`docker compose logs web` — usually a missing `ANTHROPIC_API_KEY` or a DB
permission issue (`data/` not writable).

### `data/tasks.db` permission denied

The container runs as a non-root user (`devboard`, UID 1000) by design. If you
created `./data/` as root, it will not be writable. Fix:

```bash
sudo chown -R 1000:1000 /opt/devboard/data
```

### Container restarts in a loop

```bash
docker compose logs --tail=200 web
```

The most common causes are:

1. Missing or wrong `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — `llm/factory.py`
   raises `RuntimeError: No LLM provider available`.
2. `DEVBOARD_DASHBOARD_HOST` left at its default `127.0.0.1`. Inside the container
   the app then only listens on the loopback interface and Docker's port
   publish has nothing to forward. Set `DEVBOARD_DASHBOARD_HOST=0.0.0.0` in `.env`.
3. Corrupted `data/tasks.db` after a hard crash. Restore the latest backup (see
   section 7).

### Upgrading

```bash
cd /opt/devboard
git fetch --tags
git checkout v<latest-tag>     # or: git pull origin main
docker compose pull            # if using a registry image
docker compose up -d --build
docker compose ps
```

Always take a backup first:

```bash
/opt/devboard/scripts/backup.sh
```

If something breaks, `git checkout <previous-tag>` and `docker compose up -d --build`
rolls back to the prior version.

---

## 10. Security

### Secret management

The app reads credentials (LLM API keys, etc.) from environment variables that
are injected via the `.env` file. Follow these practices to avoid leaking secrets.

#### Development (local machine)

```bash
# Create .env from the template and set permissions so only your user can read it.
cp .env.example .env
chmod 600 .env
```

Never commit `.env` to git — it is already listed in `.gitignore` and
`.dockerignore`. Verify with `git status` before every push.

#### Production (VPS / server)

**Option A — systemd EnvironmentFile (recommended for single-server setups)**

```ini
# /etc/systemd/system/devboard.service  (see §6)
[Service]
EnvironmentFile=/opt/devboard/.env
```

```bash
# Restrict read access to root only.
sudo chmod 600 /opt/devboard/.env
sudo chown root:root /opt/devboard/.env
```

**Option B — Docker secrets (Swarm mode)**

```yaml
# docker-compose.yml  (Swarm variant)
secrets:
  anthropic_key:
    external: true
services:
  web:
    secrets:
      - anthropic_key
```

Secrets are mounted as files under `/run/secrets/<name>` inside the container.
Update `llm/factory.py` to read the file path instead of the env var.

**Option C — Platform secrets (cloud / PaaS)**

Most cloud providers (Railway, Render, Fly.io, AWS ECS, GCP Cloud Run) have a
first-class "environment secrets" UI that injects variables at runtime without
ever writing them to disk. Prefer this over a plain `.env` file when available.

### Container security posture

The `docker-compose.yml` applies the following hardening options:

| Option | Effect |
|---|---|
| `security_opt: no-new-privileges:true` | Blocks privilege escalation via setuid/setgid binaries inside the container. |
| `cap_drop: ALL` | Removes all Linux capabilities; the app only needs standard network I/O on port 5000 (>1024), so no capabilities need to be re-added. |
| `read_only: true` | Mounts the container root filesystem read-only. Writes are only possible via the explicit `./data` bind-mount and the `/tmp` tmpfs. |
| `tmpfs /tmp` | Provides a small (64 MB) in-memory `/tmp` with `noexec,nosuid` flags. |

The `Dockerfile` additionally runs the process as non-root user `devboard`
(UID/GID 1000) and uses `tini` as PID 1 for correct signal handling.

### Periodic security checks

```bash
# Scan the running image for known CVEs (requires trivy).
trivy image devboard:latest

# Check that no container runs as root.
docker inspect devboard | jq '.[].Config.User'

# Verify read-only enforcement.
docker exec devboard touch /test-rw 2>&1  # expected: "Read-only file system"
```

---

## See also

- [README.md](README.md) — what the project does and how to run it locally.
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pieces fit together.
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to send a patch.
- [Dockerfile](Dockerfile) — the image this guide deploys.
- [docker-compose.yml](docker-compose.yml) — the service definition referenced
  by `docker compose up`.
