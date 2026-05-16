from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_DAILY = re.compile(r"^krstock_daily_(?P<d>\d{4}-\d{2}-\d{2})\.md$")
_RANGE = re.compile(
    r"^krstock_(?P<start>\d{4}-\d{2}-\d{2})_to_(?P<end>\d{4}-\d{2}-\d{2})\.md$"
)


@dataclass
class ReportEntry:
    slug: str
    filename: str
    start_date: str
    end_date: str
    title: str
    mtime: float
    size: int

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "filename": self.filename,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "title": self.title,
            "mtime": self.mtime,
            "size": self.size,
        }


def _title_for(start: str, end: str) -> str:
    if start == end:
        return f"{start} 민심 리포트"
    return f"{start} ~ {end} 민심 리포트"


def parse_report_path(path: Path) -> ReportEntry | None:
    name = path.name
    m = _DAILY.match(name)
    if m:
        d = m.group("d")
        stat = path.stat()
        return ReportEntry(
            slug=path.stem,
            filename=name,
            start_date=d,
            end_date=d,
            title=_title_for(d, d),
            mtime=stat.st_mtime,
            size=stat.st_size,
        )
    m = _RANGE.match(name)
    if m:
        start, end = m.group("start"), m.group("end")
        stat = path.stat()
        return ReportEntry(
            slug=path.stem,
            filename=name,
            start_date=start,
            end_date=end,
            title=_title_for(start, end),
            mtime=stat.st_mtime,
            size=stat.st_size,
        )
    return None


def list_reports(reports_dir: Path) -> list[ReportEntry]:
    if not reports_dir.is_dir():
        return []
    entries: list[ReportEntry] = []
    for path in reports_dir.glob("krstock*.md"):
        if path.is_file():
            entry = parse_report_path(path)
            if entry:
                entries.append(entry)
    entries.sort(key=lambda e: e.start_date, reverse=True)
    return entries


def read_report(reports_dir: Path, slug: str) -> str | None:
    path = reports_dir / f"{slug}.md"
    if not path.is_file() or ".." in slug or "/" in slug:
        return None
    return path.read_text(encoding="utf-8")


def format_mtime(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
