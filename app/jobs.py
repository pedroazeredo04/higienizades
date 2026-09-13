"""Background jobs: an hourly safety net and a nightly backup."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_config
from app.db import session_scope
from app.services import chores as chore_service
from app.services import household as household_service

log = logging.getLogger("higienizades.jobs")


def backfill_instances() -> None:
    """Make sure every active chore has an open occurrence.

    Completion normally queues the successor synchronously, so this only ever
    catches the odd gap: a chore created before anyone was registered, or a
    crash between marking one done and creating the next.
    """
    with session_scope() as session:
        today = household_service.load(session).today
        created = chore_service.backfill_open_instances(session, today)
        if created:
            log.info("Backfilled %s chore occurrence(s)", created)


def _database_path() -> Path | None:
    url = get_config().database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    return Path(url[len(prefix) :]).resolve()


def backup_database() -> Path | None:
    """Snapshot the database using SQLite's own backup API.

    Copying the file with `cp` while the app is running can capture a torn
    write; `.backup` is safe against a live database.
    """
    source = _database_path()
    if source is None or not source.exists():
        return None

    config = get_config()
    backup_dir = Path(config.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"higienizades-{datetime.now().strftime('%Y-%m-%d')}.db"

    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)

    snapshots = sorted(backup_dir.glob("higienizades-*.db"))
    for stale in snapshots[: -config.backup_keep]:
        stale.unlink(missing_ok=True)

    log.info("Wrote backup %s", target)
    return target


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(backfill_instances, "interval", hours=1, id="backfill")
    scheduler.add_job(backup_database, "cron", hour=3, minute=0, id="backup")
    return scheduler
