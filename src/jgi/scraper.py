from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .galleries import DEFAULT_GALLERY_KEY
from .models import PostMeta

logger = logging.getLogger(__name__)

GALLERY_ID = DEFAULT_GALLERY_KEY  # 하위 호환용 기본값
BASE = "https://gall.dcinside.com"
LIST_PATH = "/mgallery/board/lists/"
VIEW_PATH = "/mgallery/board/view/"

# DC는 차단할 때 상태코드 대신 **빈 본문(200, 0자)** 을 돌려주는 경우가 있다.
# 이걸 정상 응답으로 받아들이면 "게시글 없음"으로 조용히 수집이 끝나
# 리포트가 잘린 채로 생성된다 → 재시도 후 실패로 처리한다.
MIN_HTML_CHARS = 200


class ScrapeBlockedError(RuntimeError):
    """차단으로 추정되는 비정상적으로 짧은 응답."""

KST = timezone(timedelta(hours=9))

_RE_TIME = re.compile(r"\d{2}:\d{2}")
_RE_DATE_DOT = re.compile(r"\d{2}\.\d{2}\.\d{2}")
_RE_DATE_SLASH = re.compile(r"\d{2}/\d{2}/\d{2}")
_RE_LEADING_INT = re.compile(r"(\d+)")
_RE_MULTI_NEWLINE = re.compile(r"\n{3,}")


def list_referer(gallery_id: str = GALLERY_ID) -> str:
    return f"{BASE}{LIST_PATH}?id={gallery_id}"


_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


def build_list_url(page: int = 1, gallery_id: str = GALLERY_ID) -> str:
    return f"{BASE}{LIST_PATH}?id={gallery_id}&page={page}"


def build_view_url(no: int, gallery_id: str = GALLERY_ID) -> str:
    return f"{BASE}{VIEW_PATH}?id={gallery_id}&no={no}"


class Scraper:
    def __init__(
        self,
        min_delay: float = 0.4,
        max_delay: float = 0.9,
        timeout: float = 15.0,
        gallery_id: str = GALLERY_ID,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.gallery_id = gallery_id
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        self._last_request_at: float | None = None

    def close(self) -> None:
        self._client.close()

    def list_url(self, page: int = 1) -> str:
        return build_list_url(page, self.gallery_id)

    def view_url(self, no: int) -> str:
        return build_view_url(no, self.gallery_id)

    @property
    def list_referer(self) -> str:
        return list_referer(self.gallery_id)

    def __enter__(self) -> "Scraper":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _sleep_politely(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            target = random.uniform(self.min_delay, self.max_delay)
            if elapsed < target:
                time.sleep(target - elapsed)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=3, max=30),
        retry=retry_if_exception_type((httpx.HTTPError, ScrapeBlockedError)),
        reraise=True,
    )
    def fetch(self, url: str, referer: str | None = None) -> str:
        self._sleep_politely()
        headers = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Referer": referer or f"{BASE}/",
        }
        logger.debug("GET %s", url)
        resp = self._client.get(url, headers=headers)
        self._last_request_at = time.monotonic()
        if resp.status_code in (403, 429, 503):
            # Force retry path
            raise httpx.HTTPStatusError(
                f"blocked status {resp.status_code}",
                request=resp.request,
                response=resp,
            )
        resp.raise_for_status()
        text = resp.text
        if len(text.strip()) < MIN_HTML_CHARS:
            # 차단(빈 200) — 조용히 빈 결과로 처리하지 않고 재시도/실패시킨다.
            raise ScrapeBlockedError(
                f"빈 응답({len(text)}자) — 차단으로 추정: {url}"
            )
        return text


def _parse_dc_datetime(td_date) -> datetime | None:
    """`<td class="gall_date" title="2026-05-15 20:47:49">…</td>` → aware datetime(KST).

    Fallback: title 속성이 없을 때는 td 텍스트 (`HH:MM` 또는 `YY.MM.DD`)를 해석.
    """
    title = td_date.get("title", "").strip()
    if title:
        try:
            return datetime.strptime(title, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        except ValueError:
            pass

    text = td_date.get_text(strip=True)
    now = datetime.now(KST)
    if _RE_TIME.fullmatch(text):
        h, m = map(int, text.split(":"))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)
    if _RE_DATE_DOT.fullmatch(text):
        return datetime.strptime(text, "%y.%m.%d").replace(tzinfo=KST)
    if _RE_DATE_SLASH.fullmatch(text):
        return datetime.strptime(text, "%y/%m/%d").replace(tzinfo=KST)
    return None


def _int_or_zero(s: str) -> int:
    s = (s or "").strip().replace(",", "")
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    # DC sometimes uses 'k' for thousands, but list page usually doesn't.
    m = _RE_LEADING_INT.match(s)
    return int(m.group(1)) if m else 0


def parse_list(html: str, gallery_id: str = GALLERY_ID) -> list[PostMeta]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.gall_list")
    if table is None:
        return []

    posts: list[PostMeta] = []
    for tr in table.select("tbody tr.ub-content"):
        num_td = tr.select_one("td.gall_num")
        if num_td is None:
            continue
        num_text = num_td.get_text(strip=True)
        if not num_text.isdigit():
            # 공지/AD/설문 등은 번호가 '-' 또는 아이콘이라 스킵
            continue
        no = int(num_text)

        subj_td = tr.select_one("td.gall_subject")
        category = ""
        if subj_td is not None:
            # 말머리 셀은 폭이 좁으면 잘린 텍스트만 넣고, 원본은 툴팁
            # (`p.subject_inner#head_txt_org_*`)에 담는다.
            # 예) '🐕헛소<p class="subject_inner">🐕헛소리</p>' → '🐕헛소리'
            inner = subj_td.select_one("p.subject_inner")
            src = inner if inner is not None else subj_td
            category = src.get_text(strip=True)

        tit_td = tr.select_one("td.gall_tit")
        if tit_td is None:
            continue
        a = tit_td.select_one("a")
        title = a.get_text(strip=True) if a else tit_td.get_text(strip=True)
        href = a.get("href", "") if a else ""
        url = (
            href
            if href.startswith("http")
            else f"{BASE}{href}"
            if href
            else build_view_url(no, gallery_id)
        )

        reply_span = tit_td.select_one(".reply_num")
        comments = _int_or_zero(reply_span.get_text(strip=True).strip("[]")) if reply_span else 0

        writer_td = tr.select_one("td.gall_writer")
        author = writer_td.get("data-nick", "").strip() if writer_td else ""
        if not author and writer_td:
            author = writer_td.get_text(strip=True)

        date_td = tr.select_one("td.gall_date")
        posted_at = _parse_dc_datetime(date_td) if date_td else None
        if posted_at is None:
            continue

        count_td = tr.select_one("td.gall_count")
        views = _int_or_zero(count_td.get_text(strip=True)) if count_td else 0

        rec_td = tr.select_one("td.gall_recommend")
        recommends = _int_or_zero(rec_td.get_text(strip=True)) if rec_td else 0

        posts.append(
            PostMeta(
                no=no,
                category=category,
                title=title,
                author=author,
                posted_at=posted_at,
                views=views,
                recommends=recommends,
                comments=comments,
                url=url,
            )
        )

    return posts


def parse_view(html: str, max_chars: int = 4000) -> str:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(".write_div") or soup.select_one(".writing_view_box")
    if body is None:
        return ""

    # 잡음 태그 제거
    for tag in body(["script", "style", "iframe", "noscript"]):
        tag.decompose()
    # 광고/임베드 추정 div 제거
    for cls in ("adsbygoogle", "writing_view_link", "imgwrap_btn"):
        for el in body.select(f".{cls}"):
            el.decompose()

    text = body.get_text("\n", strip=True)
    # 연속 빈 줄 정리
    text = _RE_MULTI_NEWLINE.sub("\n\n", text)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…(이하 생략)"
    return text


def iter_list_pages(
    scraper: Scraper,
    start: int = 1,
    gallery_id: str | None = None,
) -> Iterable[tuple[int, list[PostMeta]]]:
    """페이지 1부터 무한히 yield. 호출자가 break 조건으로 끊는다."""
    gid = gallery_id or scraper.gallery_id
    referer = list_referer(gid)
    page = start
    while True:
        url = build_list_url(page, gid)
        html = scraper.fetch(url, referer=referer)
        yield page, parse_list(html, gid)
        page += 1
