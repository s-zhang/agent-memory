"""
APScheduler job definitions.
All jobs are idempotent - safe to run anytime, dedup prevents double-ingestion.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
from connectors import bluebubbles, email_imap, notion
from digest import build_digest

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # BlueBubbles pull: only register when explicitly enabled (not on Railway)
    if config.BLUEBUBBLES_PULL_ENABLED:
        scheduler.add_job(
            bluebubbles.pull_recent,
            IntervalTrigger(minutes=15),
            id="pull_bluebubbles",
            replace_existing=True,
            misfire_grace_time=60,
        )

    # Email IMAP: every 15 min
    scheduler.add_job(
        email_imap.pull_recent,
        IntervalTrigger(minutes=15),
        id="pull_email",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # Notion: every 1 hour
    scheduler.add_job(
        notion.pull_recent,
        IntervalTrigger(hours=1),
        id="pull_notion",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Nightly digest: 2am UTC
    scheduler.add_job(
        build_digest,
        CronTrigger(hour=2, minute=0, timezone="UTC"),
        id="build_digest",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    return scheduler
