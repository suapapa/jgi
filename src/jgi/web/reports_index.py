from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..galleries import DEFAULT_GALLERY, GALLERIES, Gallery, gallery_for_scope
from ..scraper import KST

# 파일 이름 규칙 (galleries.py 참고):
#   레거시/기본 갤러리 : jgi_daily_2026-09-27.md, krstock_2026-09-01_to_2026-09-07.md
#   그 외 갤러리       : jgi_tenbagger_daily_2026-09-27.md
_DAILY = re.compile(
    r"^(?:jgi|krstock)(?:_(?P<scope>[a-z0-9]+))?_daily_(?P<d>\d{4}-\d{2}-\d{2})\.md$"
)
_RANGE = re.compile(
    r"^(?:jgi|krstock)(?:_(?P<scope>[a-z0-9]+))?"
    r"_(?P<start>\d{4}-\d{2}-\d{2})_to_(?P<end>\d{4}-\d{2}-\d{2})\.md$"
)
_FEAR_GREED_RE = re.compile(r"bullish\s+([\d.]+)%\s*·\s*bearish\s+([\d.]+)%")


@dataclass
class ReportEntry:
    slug: str
    filename: str
    start_date: str
    end_date: str
    title: str
    mtime: float
    size: int
    gallery: str = DEFAULT_GALLERY.key

    def to_dict(self) -> dict:
        gallery = GALLERIES.get(self.gallery, DEFAULT_GALLERY)
        return {
            "slug": self.slug,
            "filename": self.filename,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "title": self.title,
            "mtime": self.mtime,
            "size": self.size,
            "gallery": self.gallery,
            "gallery_name": gallery.name,
            "gallery_short_name": gallery.short_name,
            "market_label": gallery.market_label,
        }


def _title_for(start: str, end: str, gallery: Gallery) -> str:
    period = start if start == end else f"{start} ~ {end}"
    return f"{gallery.short_name} · {period} 민심 리포트"


def parse_report_path(path: Path) -> ReportEntry | None:
    name = path.name
    m = _DAILY.match(name)
    if m:
        d = m.group("d")
        stat = path.stat()
        gallery = gallery_for_scope(m.group("scope"))
        return ReportEntry(
            slug=path.stem,
            filename=name,
            start_date=d,
            end_date=d,
            title=_title_for(d, d, gallery),
            mtime=stat.st_mtime,
            size=stat.st_size,
            gallery=gallery.key,
        )
    m = _RANGE.match(name)
    if m:
        start, end = m.group("start"), m.group("end")
        stat = path.stat()
        gallery = gallery_for_scope(m.group("scope"))
        return ReportEntry(
            slug=path.stem,
            filename=name,
            start_date=start,
            end_date=end,
            title=_title_for(start, end, gallery),
            mtime=stat.st_mtime,
            size=stat.st_size,
            gallery=gallery.key,
        )
    return None


def list_reports(reports_dir: Path, gallery: str | None = None) -> list[ReportEntry]:
    """`gallery`를 주면 해당 갤러리 리포트만 반환한다."""
    if not reports_dir.is_dir():
        return []
    entries: list[ReportEntry] = []
    for path in reports_dir.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if not name.endswith(".md"):
            continue
        if not (name.startswith("jgi") or name.startswith("krstock")):
            continue
        entry = parse_report_path(path)
        if entry:
            entries.append(entry)
    if gallery:
        entries = [e for e in entries if e.gallery == gallery]
    entries.sort(key=lambda e: (e.start_date, e.mtime), reverse=True)
    return entries


def read_report(reports_dir: Path, slug: str) -> str | None:
    path = reports_dir / f"{slug}.md"
    if not path.is_file() or ".." in slug or "/" in slug:
        return None
    return path.read_text(encoding="utf-8")


def format_mtime(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=KST).strftime("%Y-%m-%d %H:%M")


def extract_fear_greed_score(content: str) -> float | None:
    """감정 분포에서 공포탐욕지수 추출 (bullish% - bearish% + 50)"""
    match = _FEAR_GREED_RE.search(content)
    if not match:
        return None

    try:
        bullish = float(match.group(1))
        bearish = float(match.group(2))
        # 공포탐욕지수: 0=공포, 100=탐욕
        # bullish와 bearish의 차이를 이용해 계산
        score = (bullish - bearish) + 50
        # 0-100 범위로 제한
        return max(0, min(100, score))
    except (ValueError, IndexError):
        return None
