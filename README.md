# Amsterdam Housing Hunter

A personal, persistent Telegram alert service for new Amsterdam rental listings. It keeps missing information visible, applies a deterministic score, calculates bicycle routes only through OpenRouteService, and isolates source failures.

## Current implementation and limitations

- Implemented: SQLite persistence and additive schema upgrades, source health records, cross-platform deduplication with retained source links, listing-change alerts, configurable scoring, Dutch/English housemate, rent, area, bedroom, and availability extraction, user-specific preferences, Italian Telegram messages and command menu, activation codes/roles, inline callbacks, IMAP alert intake, Docker, backups, and recovery.
- Public HTML adapters: Pararius, IamExpat, Van der Linden, and VerhuurtBeter. Each checks `robots.txt` at runtime, fails closed when policy cannot be read, and stops on 401/403/429. Pararius only requests its robots-allowed Amsterdam studio, room, and apartment routes. No anti-bot or login controls are bypassed.
- A live scan previously extracted 41 Pararius, 23 IamExpat, and 27 VerhuurtBeter listings. The current Docker database contains 100 deduplicated listing records, including the initial recent-history window. In the first Docker check, IamExpat and VerhuurtBeter were `ACTIVE`; Pararius returned HTTP 403 and was marked `BLOCKED`; Van der Linden returned no recognized listing cards and was marked `DEGRADED`. Those statuses are runtime-dependent and visible in `/sources`.
- Disabled for automated HTML extraction: Kamernet and Funda. Their current terms explicitly prohibit automated extraction/scraping. Their user-created listing-alert emails can be fed through read-only IMAP.
- Email alert intake requires the user to set up platform alerts and provide a read-only IMAP mailbox. Mail delivery speed depends on each platform and mailbox provider; this is not a guarantee of second-level detection.
- Email intake is implemented for alert mail from Pararius, Kamernet, Funda, HuurExpert, RentHunter, Rentwebs, IamExpat, VerhuurtBeter, Van der Linden, Huure, and Facebook. The current `.env` has no IMAP mailbox configured, so these email feeds are waiting for `IMAP_HOST`, `IMAP_USERNAME`, `IMAP_PASSWORD`, and optionally `IMAP_FOLDER` / `IMAP_ALLOWED_DOMAINS`.
- Cycling uses HeiGIT's current OpenRouteService endpoints and its `cycling-regular` bicycle profile. A live route from Amsterdam Centraal to the configured Singel reference completed in 9.2 minutes over 2.27 km; listing addresses are routed separately and approximate locations are flagged.
- Telegram connectivity was verified for `@amsterdamhousing_bot`. Docker Compose is running locally with persistent named volumes and Telegram polling enabled. The configured administrator is authorized automatically on their first `/start`; that first authorization displays five listings observed in the last three days. No user has authorized in the database until they start the chat. Cloud hosting has not been provisioned.
- Public HTML structures change. Source status is shown as active only after a successful permitted check; blocked and unsupported sources remain visible in `/sources`.

## Source capability matrix

Current source research, exact URLs, permission notes, and adapter statuses are in [docs/source-capability-matrix.md](docs/source-capability-matrix.md). The matrix distinguishes an implemented adapter from a live verified source. Run one scan to check current access:

```sh
python -m app.main --once
```

This makes one request cycle through runtime policy checks. It does not contact advertisers or submit applications.

## Local setup

Requires Python 3.12+.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
cp .env.example .env
```

Edit `.env` and set:

1. `TELEGRAM_BOT_TOKEN` from BotFather.
2. `TELEGRAM_ADMIN_IDS` to your numeric Telegram ID. The admin is authorized on first `/start`.
3. `USER_AGENT` with a real contact email.
4. Optional read-only IMAP credentials for official alert emails.
5. Optional `ORS_API_KEY` for cycling geocoding and routing.

Run the bot and monitor:

```sh
python -m app.main
```

Without a Telegram token, monitoring still runs and writes to SQLite, but no alerts can be delivered. Without an admin ID, no account is initially authorized. Test policy-gated sources with `--once`; a source that cannot retrieve `robots.txt` stays degraded.

## Telegram authorization and commands

Open [@amsterdamhousing_bot](https://t.me/amsterdamhousing_bot) in Telegram and send `/start`. The configured admin ID is authorized automatically. On first authorization, the bot sends five recent listings with their original links. Use `/history 7` for up to ten records from the last seven days, or `/latest` for the five newest records. The bot cannot message a user until that user has opened the chat and sent a message.

Every authorized `/start` shows the Italian onboarding guide, the public-site and email-alert coverage, and a persistent keyboard for the latest listings, three-day history, status, sources, settings, and help. `/help` repeats the guide and command list at any time. The keyboard buttons invoke the same authorized commands.

The numeric IDs in `TELEGRAM_ADMIN_IDS` are admins. Other accounts receive no listing or profile data until an admin creates a one-time code with `/generate_code user` and the user redeems it using `/login CODE`. Codes expire after 24 hours and are stored hashed. Admins can revoke with `/revoke_user ID`.

Commands: `/start`, `/login`, `/logout`, `/profile`, `/status`, `/latest`, `/history [days]`, `/stats`, `/sources`, `/settings`, `/pause`, `/resume`, `/admin`, `/generate_code`, `/revoke_user`, `/help`.

The first authorized `/start` shows the five newest listings detected in the past three days. `/history` shows up to ten and accepts a 1–30 day window, for example `/history 7`. `/latest` shows the five newest records regardless of age.

`/settings` accepts `max_monthly`, `ideal_monthly`, and `max_cycling_minutes`. Furnishing is a preference, not an exclusion. Unknown utilities, housemates, address, or availability remain pending verification. Only confirmed hard exclusions suppress notifications.

## Scoring and routing

All weights and boundaries live in [config/scoring.toml](config/scoring.toml). The score is deterministic and persisted with each listing; data confidence is separate. See the complete reason and point calculation with **SHOW SCORE DETAILS** in Telegram.

With `ORS_API_KEY`, geocoding and cycling directions use HeiGIT's current OpenRouteService endpoints and OSM-based `cycling-regular` profile. It does not infer time from distance. Addresses without a house number are marked approximate. Without a valid route, cycling points are unverified and the listing is retained.

## Docker Compose

The local Compose deployment is already running in this project directory. Check it with `docker compose ps`; follow logs with `docker compose logs -f housing-hunter`. The named data and backup volumes persist through container rebuilds and restarts on this computer. This is 24/7 only while the computer is powered on, connected to the internet, and Docker Desktop is running.

```sh
# On a fresh machine, create and edit .env first; set the Telegram token/admin ID and a contact email in USER_AGENT.
docker compose up -d --build
docker compose logs -f housing-hunter
docker compose ps
```

SQLite lives in the named `housing-data` volume. Automated SQLite-consistent backups are created daily in `housing-backups` (14 retained). Docker restarts the service unless stopped and checks SQLite health every minute. The image uses Python's multi-architecture base image and can run on AMD64 or ARM64.

Make a manual backup:

```sh
docker compose exec housing-hunter python -m scripts.backup
```

Copy a backup out of the container volume before a risky redeploy or host replacement:

```sh
docker compose cp housing-hunter:/app/backups ./backups
```

For a local non-Docker database, restore while the service is stopped:

```sh
DATA_DIR=./data scripts/restore.sh ./backups/housing-YYYYMMDDTHHMMSSZ.sqlite3
```

For the Compose named volume, copy the backup into the stopped service's backup volume, then replace and check the database in a one-off container:

```sh
docker compose stop housing-hunter
docker compose cp ./backups/housing-YYYYMMDDTHHMMSSZ.sqlite3 housing-hunter:/app/backups/restore.sqlite3
docker compose run --rm --no-deps --entrypoint sh housing-hunter -c "if [ -f /app/data/housing.db ]; then cp /app/data/housing.db /app/backups/housing.before-restore.sqlite3; fi; cp /app/backups/restore.sqlite3 /app/data/housing.db; python -m app.main --healthcheck"
docker compose up -d housing-hunter
```

The automated backup volume is on the same host as the database. For protection against host loss, copy backups to a separate device or object store. The application does not upload data off-host by default.

## Free hosting options

### Northflank Sandbox

Northflank's current Developer Sandbox lists up to $20/month in cloud resources across two services, two jobs, and one database, with always-on service execution. Persistent disks are available but priced separately per GiB/month; account documentation also says a payment method is required to create resources, despite the pricing page's “no card needed” language. Its docs characterize the free tier as for testing/hobby use and not production. Therefore the allowance may fit this small process, but it is not an assured zero-cost, production-backed 24/7 deployment.

To try it: connect this GitHub repository, create a Dockerfile-based service, choose the smallest always-on compute plan, attach a persistent volume mounted at `/app/data` and `/app/backups`, set the variables from `.env.example` in the secret/environment settings, and deploy. Check the estimate and billing panel before leaving it running. Do not use ephemeral container storage for `DATA_DIR`.

### Oracle Cloud Always Free

Oracle currently lists Ampere A1 Always Free capacity equivalent to up to 2 OCPUs/12 GB RAM and 200 GB total block volume. Capacity can be unavailable in a home region. Oracle may reclaim an Always Free compute instance if its CPU, network, and (A1) memory usage all remain below its published idle thresholds over seven days. The monitor makes outbound requests, but uptime is not guaranteed by this repository. Oracle account creation generally requires a payment card for identity verification; Always Free eligibility and region capacity are controlled by Oracle.

1. Create an Oracle Cloud account and choose the home region carefully.
2. Create an Ubuntu ARM64 VM (`VM.Standard.A1.Flex`) within the Always Free resource limits. Keep boot/block volumes within the 200 GB free total.
3. Add an SSH ingress rule limited to your own IP. This bot uses Telegram long polling and needs no inbound application port. Permit outbound HTTPS (443); permit outbound IMAPS (993) only if you enable email ingestion.
4. SSH to the VM, install Docker Engine and Compose from Docker's official Ubuntu instructions, clone this repository, and configure `.env`.
5. Run `docker compose up -d --build`. Confirm `docker compose ps` reports healthy, then send `/status` to the bot.
6. Periodically copy `housing-*.sqlite3` backups off the VM. Named Docker volumes survive container rebuilds and VM reboots, not deletion or loss of the underlying VM/block volume.

Neither provider has been provisioned from this workspace, so deployment is prepared but not claimed as complete. Free quotas, eligibility, payment verification, regional capacity, and billing terms can change; check the provider's current account page before deployment.

## Troubleshooting

- `REQUIRES_AUTHENTICATION`: set up the platform's own alert email and read-only IMAP credentials, or sign in to that platform manually.
- `UNSUPPORTED`: current access terms do not permit the adapter to poll the site.
- `BLOCKED`: source `robots.txt`, access policy, or an HTTP 403/429 stopped requests; the adapter does not retry around the restriction.
- `DEGRADED`: source or network failed. Other source workers continue independently.
- `cycling time unverified`: set `ORS_API_KEY`; routing is never approximated using straight-line distance.
- `Telegram startup failed`: verify the token and outbound HTTPS, then inspect container logs without copying secret values into reports.

## Development

```sh
python -m pytest
python -m app.main --healthcheck
```

HTML fixtures and deterministic rule tests are in `tests/`. No test issues requests to live rental sites.
