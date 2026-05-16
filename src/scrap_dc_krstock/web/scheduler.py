from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..pipeline import ReportConfig, run_report
from ..scraper import KST

logger = logging.getLogger(__name__)


class JobState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.last_started: datetime | None = None
        self.last_finished: datetime | None = None
        self.last_error: str | None = None
        self.last_path: str | None = None

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "last_started": self.last_started.isoformat() if self.last_started else None,
                "last_finished": self.last_finished.isoformat() if self.last_finished else None,
                "last_error": self.last_error,
                "last_path": self.last_path,
            }


def yesterday_kst() -> date:
    return (datetime.now(KST) - timedelta(days=1)).date()


def run_scheduled_job(
    *,
    reports_dir: Path,
    cache_dir: Path,
    target_date: date | None = None,
    top: int = 30,
    force: bool = False,
    state: JobState | None = None,
) -> None:
    target = target_date or yesterday_kst()
    cfg = ReportConfig(
        target_date=target,
        top=top,
        output_dir=reports_dir,
        cache_dir=cache_dir,
        force=force,
    )
    if state:
        with state.lock:
            state.running = True
            state.last_started = datetime.now(KST)
            state.last_error = None
    try:
        result = run_report(cfg)
        if state:
            with state.lock:
                state.last_path = str(result.path) if result.path else None
        logger.info("스케줄 작업 완료: %s (skipped=%s)", result.path, result.skipped)
    except Exception as e:
        logger.exception("스케줄 작업 실패")
        if state:
            with state.lock:
                state.last_error = str(e)
        raise
    finally:
        if state:
            with state.lock:
                state.running = False
                state.last_finished = datetime.now(KST)


def create_scheduler(
    reports_dir: Path,
    cache_dir: Path,
    state: JobState,
    cron: str | None = None,
) -> BackgroundScheduler:
    cron_expr = cron or os.getenv("SCHEDULE_CRON", "0 7 * * *")
    parts = cron_expr.split()
    if len(parts) == 5:
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone="Asia/Seoul",
        )
    else:
        trigger = CronTrigger.from_crontab(cron_expr, timezone="Asia/Seoul")

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    def _job() -> None:
        run_scheduled_job(reports_dir=reports_dir, cache_dir=cache_dir, state=state)

    scheduler.add_job(_job, trigger=trigger, id="daily_report", replace_existing=True)
    return scheduler
