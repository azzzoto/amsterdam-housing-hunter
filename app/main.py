from __future__ import annotations

import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx

from app.bot.notifications import TelegramNotifier
from app.bot.telegram_bot import ITALIAN_COMMANDS, create_application
from app.config import ROOT, load_scoring_settings, settings
from app.database import Database
from app.monitoring.orchestrator import Orchestrator
from app.routing import CyclingRouter
from app.scrapers.registry import build_adapters


def configure_logging(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # httpx logs full request URLs at INFO; Telegram and ORS URLs/credentials must stay out of logs.
    for noisy_logger in ("httpx", "httpcore", "telegram", "telegram.request"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root_logger.addHandler(console)
    file_handler = RotatingFileHandler(data_dir / "application.log", maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


async def backup_loop(db: Database, backup_dir: Path) -> None:
    while True:
        try:
            destination = await asyncio.to_thread(db.create_backup, backup_dir)
            logging.getLogger(__name__).info("SQLite backup created: %s", destination.name)
            backups = sorted(backup_dir.glob("housing-*.sqlite3"), key=lambda path: path.stat().st_mtime, reverse=True)
            for old in backups[14:]:
                old.unlink(missing_ok=True)
        except Exception:
            logging.getLogger(__name__).exception("Automated database backup failed")
        await asyncio.sleep(24 * 60 * 60)


async def run(once: bool = False, healthcheck: bool = False) -> None:
    configure_logging(settings.data_dir)
    db = Database(settings.database_url, settings.data_dir)
    if healthcheck:
        if not db.healthcheck():
            raise SystemExit(1)
        db.close()
        return

    scoring = load_scoring_settings()
    timeout = httpx.Timeout(settings.http_timeout)
    limits = httpx.Limits(max_connections=settings.max_concurrent_requests + 2, max_keepalive_connections=settings.max_concurrent_requests)
    async with httpx.AsyncClient(headers={"User-Agent": settings.user_agent}, timeout=timeout, limits=limits) as client:
        semaphore = asyncio.Semaphore(settings.max_concurrent_requests)
        adapters = build_adapters(settings, client, semaphore, db)
        router = CyclingRouter(settings, db, client, scoring["cycling"]["reference_address"])
        application = None
        notifier = None
        if settings.telegram_token and not once:
            application = create_application(settings, db)
            try:
                await application.initialize()
                try:
                    await application.bot.set_my_commands(ITALIAN_COMMANDS)
                except Exception as exc:
                    logging.getLogger(__name__).warning("Could not update Telegram command menu (%s)", type(exc).__name__)
                await application.start()
                if application.updater:
                    await application.updater.start_polling(drop_pending_updates=False)
                notifier = TelegramNotifier(application.bot, db, scoring)
                logging.getLogger(__name__).info("Telegram polling started")
            except Exception as exc:
                logging.getLogger(__name__).error("Telegram startup failed (%s); monitoring will continue without alerts", type(exc).__name__)
                if application:
                    try:
                        await application.shutdown()
                    except Exception:
                        pass
                application = None
        else:
            logging.getLogger(__name__).warning("TELEGRAM_BOT_TOKEN is not configured; alerts cannot be delivered")

        if not settings.telegram_admin_ids and application:
            logging.getLogger(__name__).warning("No TELEGRAM_ADMIN_IDS configured; no account can initially be authorized")
        orchestrator = Orchestrator(db, adapters, settings, scoring, router, notifier)
        if once:
            await orchestrator.scan_once()
            for row in db.source_rows():
                logging.getLogger(__name__).info("Source %s: %s; last_error=%s", row["name"], row["status"], row["last_error"] or "none")
        else:
            backup_task = asyncio.create_task(backup_loop(db, settings.backup_dir))
            monitor_task = asyncio.create_task(orchestrator.run())
            try:
                await monitor_task
            finally:
                backup_task.cancel()
                await asyncio.gather(backup_task, return_exceptions=True)
                if application:
                    if application.updater and application.updater.running:
                        await application.updater.stop()
                    await application.stop()
                    await application.shutdown()
    db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Amsterdam Housing Hunter")
    parser.add_argument("--once", action="store_true", help="Run one source scan and exit")
    parser.add_argument("--healthcheck", action="store_true", help="Check SQLite connectivity and exit")
    args = parser.parse_args()
    try:
        asyncio.run(run(once=args.once, healthcheck=args.healthcheck))
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Shutdown requested")


if __name__ == "__main__":
    main()
