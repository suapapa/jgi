from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .models import AnalysisResult, Post, PostMeta


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.0f}%" if v <= 1.0 else f"{v:.0f}%"


def _sentiment_emoji(s: str) -> str:
    return {
        "bullish": "🟢 강세",
        "bearish": "🔴 약세",
        "neutral": "⚪ 중립",
        "mixed": "🟡 혼조",
    }.get(s, s)


def render_markdown(
    result: AnalysisResult,
    all_metas: list[PostMeta],
    top_posts: list[Post],
    start: datetime,
    end: datetime,
    pages_scanned: int,
) -> str:
    sb = result.sentiment_breakdown
    sb_line = " · ".join(
        f"{k} {_fmt_pct(v)}" for k, v in sb.items()
    ) if sb else "—"

    lines: list[str] = []
    lines.append(f"# 한국주식 갤러리 민심 리포트 ({start:%Y-%m-%d} ~ {end:%Y-%m-%d})")
    lines.append("")
    lines.append("## 한눈에 보기")
    lines.append(f"- 종합 감정: **{_sentiment_emoji(result.overall_sentiment)}**")
    lines.append(f"- 감정 분포: {sb_line}")
    lines.append(f"- 수집 게시글: {len(all_metas)}건 · 본문 분석: {len(top_posts)}건 · 스캔 페이지: {pages_scanned}")
    if result.summary:
        lines.append("")
        lines.append("### 요약")
        lines.append(result.summary)

    lines.append("")
    lines.append("## 화제 종목")
    if result.hot_tickers:
        lines.append("")
        lines.append("| 종목 | 언급 수 | 어조 |")
        lines.append("|---|---:|---|")
        for t in result.hot_tickers:
            lines.append(f"| {t.ticker} | {t.mentions} | {_sentiment_emoji(t.sentiment)} |")
    else:
        lines.append("(LLM이 추출하지 못함)")

    lines.append("")
    lines.append("## 주요 화제")
    if result.key_themes:
        for th in result.key_themes:
            lines.append(f"- {th}")
    else:
        lines.append("- (없음)")

    lines.append("")
    lines.append("## 대표 의견")
    if result.notable_quotes:
        for q in result.notable_quotes:
            meta = []
            if q.title:
                meta.append(f"제목: {q.title}")
            if q.views:
                meta.append(f"조회 {q.views}")
            if q.recommends:
                meta.append(f"추천 {q.recommends}")
            meta_str = f" — ({', '.join(meta)})" if meta else ""
            lines.append(f"> {q.quote}{meta_str}")
            lines.append("")
    else:
        lines.append("- (없음)")

    lines.append("")
    lines.append("## 우려/리스크")
    if result.risks:
        for r in result.risks:
            lines.append(f"- {r}")
    else:
        lines.append("- (없음)")

    lines.append("")
    lines.append("## 본문 분석 대상 (조회/추천 순)")
    lines.append("")
    lines.append("| # | 제목 | 조회 | 추천 | 댓글 | 작성일 | 링크 |")
    lines.append("|---:|---|---:|---:|---:|---|---|")
    for i, p in enumerate(top_posts, 1):
        title_safe = p.title.replace("|", "\\|")
        lines.append(
            f"| {i} | {title_safe} | {p.views} | {p.recommends} | {p.comments} | "
            f"{p.posted_at:%Y-%m-%d %H:%M} | [열기]({p.url}) |"
        )

    lines.append("")
    lines.append("---")
    lines.append(f"_생성: {datetime.now():%Y-%m-%d %H:%M:%S}_")

    return "\n".join(lines)


def report_filename(start: datetime, end: datetime, *, daily: bool = False) -> str:
    if daily:
        return f"krstock_daily_{start:%Y-%m-%d}.md"
    end_inclusive = end - timedelta(seconds=1) if end > start else end
    if start.date() == end_inclusive.date():
        return f"krstock_{start:%Y-%m-%d}_to_{end_inclusive:%Y-%m-%d}.md"
    return f"krstock_{start:%Y-%m-%d}_to_{end_inclusive:%Y-%m-%d}.md"


def write_report(
    text: str,
    output_dir: str | Path,
    start: datetime,
    end: datetime,
    *,
    daily: bool = False,
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / report_filename(start, end, daily=daily)
    path.write_text(text, encoding="utf-8")
    return path
