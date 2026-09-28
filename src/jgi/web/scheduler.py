from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..galleries import Gallery, resolve_galleries
from ..pipeline import ReportConfig, run_report
from ..scraper import KST

logger = logging.getLogger(__name__)


def configured_galleries(value: str | None = None) -> list[Gallery]:
    """`GALLERIES` 환경변수(예: `krstock,tenbagger`) → Gallery 목록. 미설정 시 전체."""
    raw = value if value is not None else os.getenv("GALLERIES")
    return resolve_galleries(raw)


class JobState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.last_started: datetime | None = None
        self.last_finished: datetime | None = None
        self.last_error: str | None = None
        self.last_path: str | None = None
        self.last_paths: dict[str, str] = {}

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "last_started": self.last_started.isoformat() if self.last_started else None,
                "last_finished": self.last_finished.isoformat() if self.last_finished else None,
                "last_error": self.last_error,
                "last_path": self.last_path,
                "last_paths": dict(self.last_paths),
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
    galleries: list[Gallery] | None = None,
    state: JobState | None = None,
) -> None:
    """선택된 갤러리들의 리포트를 순서대로 생성한다 (한 갤러리 실패가 나머지를 막지 않음)."""
    target = target_date or yesterday_kst()
    gallery_list = galleries if galleries is not None else configured_galleries()

    started = datetime.now(KST)
    if state:
        with state.lock:
            state.running = True
            state.last_started = started
            state.last_error = None

    errors: list[str] = []
    try:
        for gallery in gallery_list:
            cfg = ReportConfig(
                target_date=target,
                top=top,
                output_dir=reports_dir,
                cache_dir=cache_dir,
                force=force,
                gallery=gallery,
            )
            try:
                result = run_report(cfg)
            except Exception as e:  # 갤러리 하나 실패해도 나머지는 계속
                logger.exception("%s 리포트 생성 실패", gallery.name)
                errors.append(f"{gallery.key}: {e}")
                continue
            logger.info(
                "%s 리포트 완료: %s (skipped=%s)", gallery.name, result.path, result.skipped
            )
            if state and result.path:
                with state.lock:
                    state.last_paths[gallery.key] = str(result.path)
                    state.last_path = str(result.path)
    finally:
        if state:
            with state.lock:
                state.running = False
                state.last_finished = datetime.now(KST)
                if errors:
                    state.last_error = " / ".join(errors)

    if errors and len(errors) == len(gallery_list):
        raise RuntimeError("; ".join(errors))


def create_scheduler(
    reports_dir: Path,
    cache_dir: Path,
    state: JobState,
    cron: str | None = None,
    galleries: list[Gallery] | None = None,
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
        run_scheduled_job(
            reports_dir=reports_dir,
            cache_dir=cache_dir,
            galleries=galleries,
            state=state,
        )

    scheduler.add_job(_job, trigger=trigger, id="daily_report", replace_existing=True)
    return scheduler
