from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler

from .pipeline import ReportConfig, checkpoint_for, resolve_window, run_report

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_time=False)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="jgi",
        description="DC인사이드 한국주식 갤러리 일주일 민심 분석",
    )
    p.add_argument("--days", type=int, default=7, help="수집 기간 (일, 기본 7)")
    p.add_argument(
        "--date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="달력 하루(KST 00:00~23:59) 수집 — 지정 시 --days 무시",
    )
    p.add_argument("--top", type=int, default=30, help="본문 분석할 상위 게시글 수 (기본 30)")
    p.add_argument(
        "--recommend-weight",
        type=float,
        default=3.0,
        help="랭킹에서 추천수 가중치 (기본 3.0)",
    )
    p.add_argument("--output", default="reports", help="리포트 출력 디렉토리")
    p.add_argument("--model", default=None, help="LLM 모델 이름 (OPENAI_MODEL env 대신 override)")
    p.add_argument(
        "--max-pages",
        type=int,
        default=2000,
        help="안전장치: 스캔할 최대 페이지 수 (기본 2000)",
    )
    p.add_argument(
        "--body-max-chars",
        type=int,
        default=3000,
        help="본문 1건당 LLM에 보낼 최대 글자 수 (기본 3000)",
    )
    p.add_argument("--min-delay", type=float, default=0.4, help="요청 사이 최소 대기 (초)")
    p.add_argument("--max-delay", type=float, default=0.9, help="요청 사이 최대 대기 (초)")
    p.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 JSON 저장")
    p.add_argument("--cache-dir", default="cache", help="체크포인트 디렉토리")
    p.add_argument("--fresh", action="store_true", help="캐시 초기화 후 재수집")
    p.add_argument("--refresh-analysis", action="store_true", help="LLM 분석만 재실행")
    p.add_argument("--force", action="store_true", help="기존 리포트가 있어도 다시 생성")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG 로깅")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    _setup_logging(args.verbose)

    target_date = date.fromisoformat(args.date) if args.date else None
    cfg = ReportConfig(
        days=None if target_date else args.days,
        target_date=target_date,
        top=args.top,
        recommend_weight=args.recommend_weight,
        output_dir=Path(args.output),
        cache_dir=Path(args.cache_dir),
        model=args.model,
        max_pages=args.max_pages,
        body_max_chars=args.body_max_chars,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        fresh=args.fresh,
        refresh_analysis=args.refresh_analysis,
        dry_run=args.dry_run,
        force=args.force,
        on_meta_progress=lambda page, page_new, total: console.print(
            f"  · page {page}: +{page_new} (누적 {total})", style="dim"
        ),
        on_body_progress=lambda i, n, post, cached: console.print(
            f"  · {'cache' if cached else 'fetch'} {i}/{n} no={post.no} "
            f"본문 {len(post.body)}자: {post.title[:50]}",
            style="dim",
        ),
    )

    start, end, is_daily = resolve_window(cfg)

    console.print(
        f"[bold]수집 기간[/bold]: {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M} (KST)"
        + (" [dim](달력 하루)[/dim]" if is_daily else "")
    )

    if args.fresh:
        console.print(f"[yellow]--fresh: 캐시 초기화[/yellow]")
    elif args.refresh_analysis:
        console.print("[yellow]--refresh-analysis: 분석 캐시만 삭제[/yellow]")

    cp = checkpoint_for(cfg, start, is_daily)
    console.print(f"[dim]캐시: {cp.summary()}[/dim]")

    console.print("[bold]1) 메타데이터 수집 중…[/bold]")
    try:
        result = run_report(cfg)
    except RuntimeError as e:
        console.print(f"[bold red]{e}[/bold red]")
        return 1

    if result.skipped:
        console.print(f"[yellow]기존 리포트 사용:[/yellow] {result.path}")
        return 0

    console.print(
        f"  → 총 [bold]{result.metas_count}[/bold]건 · 상위 본문 {result.top_count}건 "
        f"({result.pages_scanned}페이지)"
    )

    if args.dry_run:
        console.print(f"[bold green]Dry-run 저장:[/bold green] {result.path}")
        return 0

    console.print(f"[bold green]리포트 저장:[/bold green] {result.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
