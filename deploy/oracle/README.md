# Oracle Cloud deployment

This configuration runs one ARM64-compatible Docker container on an Ubuntu VM. The VM and Docker Compose, not GitHub Actions, own the continuous process. GitHub Actions only transfers the Compose configuration, temporarily authenticates to GHCR, starts the requested image, and verifies Docker's health check.

## One-time VM setup

1. Create an Oracle Cloud Ubuntu ARM64 VM in the tenancy's home region. The Always Free Ampere A1 allowance currently totals at most 2 OCPUs, 12 GB RAM, and 200 GB of block volume for eligible accounts. Capacity is region-dependent and Oracle may reclaim instances it classifies as idle; check current Always Free terms and capacity before relying on this for urgent housing alerts.
2. Create an SSH key restricted to your workstation and add its public key to the VM. Permit inbound SSH only from your IP. This bot needs outbound HTTPS; it does not need a public HTTP port.
3. Install Docker Engine and the Docker Compose plugin using Docker's official Ubuntu instructions. Add your login user to the `docker` group and reconnect.
4. Create `/opt/amsterdam-housing-hunter`, then create `/opt/amsterdam-housing-hunter/.env` on the VM. Copy values from `.env.example` and fill in production Telegram, admin, contact, and optional routing credentials. The file is never copied from GitHub Actions; it stays on the VM.
5. In repository **Settings → Secrets and variables → Actions**, create variables `DEPLOY_TARGET=oracle`, `ORACLE_HOST` (VM public IP or DNS name), `ORACLE_USER` (Ubuntu login), and `ORACLE_KNOWN_HOSTS` (the verified SSH host-key line). Add secret `ORACLE_SSH_PRIVATE_KEY` with the private key dedicated to this deploy workflow.
6. Push to `main`. GitHub Actions publishes the image, uses its short-lived `GITHUB_TOKEN` to pull the private GHCR package, uploads `deploy/oracle/compose.yaml`, starts/restarts the service, and waits for Docker health to become `healthy`.

The named volumes `housing-data` and `housing-backups` live in Docker's persistent storage on the VM. They survive container replacement and VM reboot, but not deletion or loss of the VM's block volume. Copy backups off the VM regularly:

```sh
ssh ubuntu@YOUR_VM 'docker exec amsterdam-housing-hunter python -m scripts.backup'
ssh ubuntu@YOUR_VM 'docker cp amsterdam-housing-hunter:/app/backups/. ./housing-backups/'
```

The `.env` file is the runtime secret store on the VM; keep it mode `600` and do not commit it. The SSH key and any repository action secrets remain in GitHub's encrypted secret store. The registry password is only present in an ephemeral Actions token/config during a deployment and is removed afterward.

## Health, logs, restart, and database recovery

```sh
ssh ubuntu@YOUR_VM 'cd /opt/amsterdam-housing-hunter && docker compose -p amsterdam-housing-hunter -f compose.yaml ps'
ssh ubuntu@YOUR_VM 'cd /opt/amsterdam-housing-hunter && docker compose -p amsterdam-housing-hunter -f compose.yaml logs --tail=100 housing-hunter'
ssh ubuntu@YOUR_VM 'sudo systemctl status docker'
```

Docker uses `restart: unless-stopped` and the database health command every minute. To restore an off-host SQLite backup, stop the service, copy the backup into `/app/backups/restore.sqlite3`, replace `/app/data/housing.db` while stopped, run `python -m app.main --healthcheck`, then start the service. Keep a copy of the current DB before replacing it.

## Roll back

From **Actions → Test, publish, and deploy → Run workflow**, choose `oracle` and provide a previously published `sha-<40-character-commit-sha>` tag. The workflow pulls and restarts that exact image while retaining the named database and backup volumes.

Oracle Always Free quotas, home-region capacity, idle-instance reclamation, account verification, and pricing are controlled by Oracle and may change. See [Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
