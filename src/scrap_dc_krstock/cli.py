from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler

from .analyzer import Analyzer
from .collector import collect_meta_since, default_cutoff, fetch_bodies
from .ranker import select_top, score
from .reporter import render_markdown, write_report
from .scraper import KST, Scraper

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_time=False)],
    )
    # 외부 라이브러리는 시끄러우니 INFO 이상으로 올림
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="scrap-dc-krstock",
        description="DC인사이드 한국주식 갤러리 일주일 민심 분석",
    )
    p.add_argument("--days", type=int, default=7, help="수집 기간 (일, 기본 7)")
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
        help="안전장치: 스캔할 최대 페이지 수 (기본 2000, 7일치 ~1400페이지 추정)",
    )
    p.add_argument(
        "--body-max-chars",
        type=int,
        default=3000,
        help="본문 1건당 LLM에 보낼 최대 글자 수 (기본 3000)",
    )
    p.add_argument(
        "--min-delay",
        type=float,
        default=0.4,
        help="요청 사이 최소 대기 (초, 기본 0.4)",
    )
    p.add_argument(
        "--max-delay",
        type=float,
        default=0.9,
        help="요청 사이 최대 대기 (초, 기본 0.9)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="LLM 호출 없이 수집+랭킹 결과를 JSON으로 저장 (디버깅)",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG 로깅")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    _setup_logging(args.verbose)

    cutoff = default_cutoff(args.days)
    end = datetime.now(KST)
    console.print(
        f"[bold]수집 기간[/bold]: {cutoff:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M} (KST)"
    )

    # 1) 메타데이터 수집
    pages_scanned = 0

    def _meta_progress(page: int, page_new: int, total: int) -> None:
        nonlocal pages_scanned
        pages_scanned = page
        console.print(f"  · page {page}: +{page_new} (누적 {total})", style="dim")

    with Scraper(min_delay=args.min_delay, max_delay=args.max_delay) as scraper:
        console.print("[bold]1) 메타데이터 수집 중…[/bold]")
        metas = collect_meta_since(
            scraper,
            cutoff,
            max_pages=args.max_pages,
            progress=_meta_progress,
        )
        console.print(
            f"  → 총 [bold]{len(metas)}[/bold]건 수집 ({pages_scanned}페이지 스캔)"
        )

        # 2) 상위 N개 선정 + 본문 크롤링
        top_metas = select_top(metas, args.top, recommend_weight=args.recommend_weight)
        console.print(
            f"[bold]2) 상위 {len(top_metas)}개 본문 크롤링…[/bold]"
            f" (가중치 추천×{args.recommend_weight})"
        )

        def _body_progress(i: int, n: int, post) -> None:
            console.print(
                f"  · [{i}/{n}] no={post.no} 본문 {len(post.body)}자: {post.title[:50]}",
                style="dim",
            )

        top_posts = fetch_bodies(
            scraper,
            top_metas,
            max_chars=args.body_max_chars,
            progress=_body_progress,
        )

    # dry-run: LLM 호출 없이 JSON으로 저장
    if args.dry_run:
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"krstock_dryrun_{end:%Y-%m-%d_%H%M%S}.json"
        dump = {
            "start": cutoff.isoformat(),
            "end": end.isoformat(),
            "pages_scanned": pages_scanned,
            "metas": [m.model_dump(mode="json") for m in metas],
            "top_posts": [p.model_dump(mode="json") for p in top_posts],
            "ranking": [
                {"no": m.no, "score": score(m, args.recommend_weight), "title": m.title}
                for m in top_metas
            ],
        }
        path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[bold green]Dry-run 결과 저장:[/bold green] {path}")
        return 0

    # 3) LLM 분석
    console.print("[bold]3) LLM 분석…[/bold]")
    analyzer = Analyzer(model=args.model)
    result = analyzer.analyze(metas, top_posts)

    # 4) 리포트 작성
    console.print("[bold]4) 리포트 작성…[/bold]")
    md = render_markdown(
        result,
        all_metas=metas,
        top_posts=top_posts,
        start=cutoff,
        end=end,
        pages_scanned=pages_scanned,
    )
    path = write_report(md, args.output, cutoff, end)
    console.print(f"[bold green]리포트 저장:[/bold green] {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
