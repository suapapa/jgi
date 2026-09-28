from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler

from .galleries import DEFAULT_GALLERY, GALLERIES, Gallery, resolve_galleries
from .pipeline import ReportConfig, checkpoint_for, resolve_window, run_report
from .scraper import ScrapeBlockedError

console = Console()


def _setup_logging(verbose: bool) -> None:
    from datetime import datetime, timezone, timedelta
    from rich.text import Text

    KST = timezone(timedelta(hours=9))
    logging.Formatter.converter = lambda *args: datetime.now(KST).timetuple()

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_time=True,
                log_time_format=lambda dt: Text(datetime.now(KST).strftime("[%X KST]"))
            )
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="jgi",
        description="DC인사이드 주식 갤러리(한국주식/해외주식) 민심 분석",
    )
    p.add_argument(
        "--gallery",
        default=None,
        metavar="KEY[,KEY...]",
        help="수집할 갤러리: "
        + " | ".join(f"{k}({g.short_name})" for k, g in GALLERIES.items())
        + " — 쉼표로 여러 개, 'all'은 전체 (기본: krstock)",
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
        default=None,
        help="안전장치: 스캔할 최대 페이지 수 (기본: 갤러리별 설정)",
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


def _build_config(args: argparse.Namespace, gallery: Gallery) -> ReportConfig:
    target_date = date.fromisoformat(args.date) if args.date else None

    def meta_progress(page: int, page_new: int, total: int) -> None:
        console.print(
            f"  · page {page}: +{page_new} (누적 {total})", style="dim"
        )

    def body_progress(i: int, n: int, post, cached: bool) -> None:
        console.print(
            f"  · {'cache' if cached else 'fetch'} {i}/{n} no={post.no} "
            f"본문 {len(post.body)}자: {post.title[:50]}",
            style="dim",
        )

    return ReportConfig(
        days=None if target_date else args.days,
        target_date=target_date,
        top=args.top,
        recommend_weight=args.recommend_weight,
        output_dir=Path(args.output),
        cache_dir=Path(args.cache_dir),
        model=args.model,
        max_pages=args.max_pages or gallery.max_pages,
        body_max_chars=args.body_max_chars,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        fresh=args.fresh,
        refresh_analysis=args.refresh_analysis,
        dry_run=args.dry_run,
        force=args.force,
        gallery=gallery,
        on_meta_progress=meta_progress,
        on_body_progress=body_progress,
    )


def run_one(args: argparse.Namespace, gallery: Gallery, many: bool) -> int:
    """갤러리 하나에 대한 수집→분석→리포트. 실패 시 1 반환."""
    cfg = _build_config(args, gallery)
    start, end, is_daily = resolve_window(cfg)

    label = gallery.name
    if many:
        console.print(f"\n[bold cyan]━━ {label} ━━[/bold cyan]")
    console.print(
        f"[bold]수집 기간[/bold]: {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M} (KST)"
        + (" [dim](달력 하루)[/dim]" if is_daily else "")
    )
    console.print(f"[dim]갤러리: {label} (id={gallery.gallery_id}) · {gallery.url}[/dim]")

    if args.fresh:
        console.print("[yellow]--fresh: 캐시 초기화[/yellow]")
    elif args.refresh_analysis:
        console.print("[yellow]--refresh-analysis: 분석 캐시만 삭제[/yellow]")

    cp = checkpoint_for(cfg, start, is_daily)
    console.print(f"[dim]캐시: {cp.summary()}[/dim]")

    console.print("[bold]1) 메타데이터 수집 중…[/bold]")
    try:
        result = run_report(cfg)
    except ScrapeBlockedError as e:
        console.print(f"[bold red]DC인사이드가 응답을 차단한 것으로 보입니다:[/bold red] {e}")
        console.print(
            "[dim]잠시(수 분~수십 분) 후 다시 실행하거나 "
            "--min-delay/--max-delay를 늘려보세요. 같은 캐시로 재실행하면 이어서 수집합니다.[/dim]"
        )
        return 1
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    _setup_logging(args.verbose)

    try:
        # 기본은 기존과 동일하게 한국주식 갤러리 하나 (여러 개는 쉼표 또는 all)
        galleries = (
            resolve_galleries(args.gallery) if args.gallery else [DEFAULT_GALLERY]
        )
    except ValueError as e:
        console.print(f"[bold red]{e}[/bold red]")
        return 2

    failures = 0
    for gallery in galleries:
        failures += run_one(args, gallery, many=len(galleries) > 1)

    if len(galleries) > 1:
        console.print(
            f"\n[bold]{len(galleries) - failures}/{len(galleries)}[/bold] 갤러리 완료"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
