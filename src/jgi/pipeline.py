from __future__ import annotations

import fcntl
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from .analyzer import Analyzer
from .checkpoint import RunCheckpoint
from .collector import calendar_window, collect_meta_since, default_cutoff, fetch_bodies
from .ranker import select_top
from .reporter import render_markdown, report_filename, write_report
from .scraper import KST, Scraper

logger = logging.getLogger(__name__)

ProgressMeta = Callable[[int, int, int], None]
ProgressBody = Callable[[int, int, object, bool], None]


@dataclass
class ReportConfig:
    days: int | None = 7
    target_date: date | None = None
    top: int = 30
    recommend_weight: float = 3.0
    output_dir: Path = field(default_factory=lambda: Path("reports"))
    cache_dir: Path = field(default_factory=lambda: Path("cache"))
    model: str | None = None
    max_pages: int = 2000
    body_max_chars: int = 3000
    min_delay: float = 0.4
    max_delay: float = 0.9
    fresh: bool = False
    refresh_analysis: bool = False
    dry_run: bool = False
    force: bool = False
    on_meta_progress: ProgressMeta | None = None
    on_body_progress: ProgressBody | None = None


@dataclass
class ReportRunResult:
    path: Path | None
    start: datetime
    end: datetime
    metas_count: int
    top_count: int
    pages_scanned: int
    skipped: bool = False


def resolve_window(cfg: ReportConfig) -> tuple[datetime, datetime, bool]:
    """(start, end, is_daily_calendar)."""
    if cfg.target_date is not None:
        start, end = calendar_window(cfg.target_date)
        return start, end, True
    days = cfg.days if cfg.days is not None else 7
    end = datetime.now(KST)
    start = default_cutoff(days)
    return start, end, False


def checkpoint_for(cfg: ReportConfig, start: datetime, is_daily: bool) -> RunCheckpoint:
    if is_daily and cfg.target_date is not None:
        run_id = f"cal_{cfg.target_date:%Y-%m-%d}"
        return RunCheckpoint(cfg.cache_dir, run_id=run_id)
    days = cfg.days if cfg.days is not None else 7
    return RunCheckpoint(cfg.cache_dir, days=days)


def expected_report_path(cfg: ReportConfig, start: datetime, end: datetime, is_daily: bool) -> Path:
    fname = report_filename(start, end, daily=is_daily)
    return cfg.output_dir / fname


def run_report(cfg: ReportConfig) -> ReportRunResult:
    start, end, is_daily = resolve_window(cfg)
    out_path = expected_report_path(cfg, start, end, is_daily)

    if out_path.exists() and not cfg.force and not cfg.dry_run:
        logger.info("리포트 이미 존재, 스킵: %s", out_path)
        return ReportRunResult(
            path=out_path,
            start=start,
            end=end,
            metas_count=0,
            top_count=0,
            pages_scanned=0,
            skipped=True,
        )

    lock_path = cfg.cache_dir / ".run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        raise RuntimeError("다른 리포트 생성 작업이 실행 중입니다") from None

    try:
        return _run_report_locked(cfg, start, end, is_daily, out_path)
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def _run_report_locked(
    cfg: ReportConfig,
    start: datetime,
    end: datetime,
    is_daily: bool,
    out_path: Path,
) -> ReportRunResult:
    checkpoint = checkpoint_for(cfg, start, is_daily)
    if cfg.fresh:
        checkpoint.reset()
    elif cfg.refresh_analysis:
        checkpoint.reset_analysis()

    pages_scanned = 0

    def _meta_progress(page: int, page_new: int, total: int) -> None:
        nonlocal pages_scanned
        pages_scanned = page
        if cfg.on_meta_progress:
            cfg.on_meta_progress(page, page_new, total)

    with Scraper(min_delay=cfg.min_delay, max_delay=cfg.max_delay) as scraper:
        metas = collect_meta_since(
            scraper,
            start,
            end=end if is_daily else None,
            max_pages=cfg.max_pages,
            progress=_meta_progress,
            checkpoint=checkpoint,
        )
        pages_scanned = max(
            pages_scanned, int(checkpoint.load_state().get("last_scanned_page", 0))
        )

        top_metas = select_top(metas, cfg.top, recommend_weight=cfg.recommend_weight)

        def _body_progress(i: int, n: int, post, cached: bool = False) -> None:
            if cfg.on_body_progress:
                cfg.on_body_progress(i, n, post, cached)

        top_posts = fetch_bodies(
            scraper,
            top_metas,
            max_chars=cfg.body_max_chars,
            progress=_body_progress,
            checkpoint=checkpoint,
        )

    if cfg.dry_run:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        path = cfg.output_dir / f"jgi_dryrun_{datetime.now(KST):%Y-%m-%d_%H%M%S}.json"
        from .ranker import score

        dump = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "pages_scanned": pages_scanned,
            "metas": [m.model_dump(mode="json") for m in metas],
            "top_posts": [p.model_dump(mode="json") for p in top_posts],
            "ranking": [
                {"no": m.no, "score": score(m, cfg.recommend_weight), "title": m.title}
                for m in top_metas
            ],
        }
        path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
        return ReportRunResult(
            path=path,
            start=start,
            end=end,
            metas_count=len(metas),
            top_count=len(top_posts),
            pages_scanned=pages_scanned,
        )

    cached_result = checkpoint.load_analysis()
    if cached_result is not None and not cfg.refresh_analysis:
        result = cached_result
    else:
        analyzer = Analyzer(model=cfg.model)
        result = analyzer.analyze(metas, top_posts)
        checkpoint.save_analysis(result)

    display_end = end - timedelta(seconds=1) if is_daily else end
    md = render_markdown(
        result,
        all_metas=metas,
        top_posts=top_posts,
        start=start,
        end=display_end,
        pages_scanned=pages_scanned,
    )
    path = write_report(md, cfg.output_dir, start, end, daily=is_daily)
    return ReportRunResult(
        path=path,
        start=start,
        end=end,
        metas_count=len(metas),
        top_count=len(top_posts),
        pages_scanned=pages_scanned,
    )
