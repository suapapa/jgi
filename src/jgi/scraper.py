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

from .models import PostMeta

logger = logging.getLogger(__name__)

GALLERY_ID = "krstock"
BASE = "https://gall.dcinside.com"
LIST_PATH = "/mgallery/board/lists/"
VIEW_PATH = "/mgallery/board/view/"

KST = timezone(timedelta(hours=9))

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


def build_list_url(page: int = 1) -> str:
    return f"{BASE}{LIST_PATH}?id={GALLERY_ID}&page={page}"


def build_view_url(no: int) -> str:
    return f"{BASE}{VIEW_PATH}?id={GALLERY_ID}&no={no}"


class Scraper:
    def __init__(
        self,
        min_delay: float = 0.4,
        max_delay: float = 0.9,
        timeout: float = 15.0,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
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
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((httpx.HTTPError,)),
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
        return resp.text


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
    if re.fullmatch(r"\d{2}:\d{2}", text):
        h, m = map(int, text.split(":"))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", text):
        return datetime.strptime(text, "%y.%m.%d").replace(tzinfo=KST)
    if re.fullmatch(r"\d{2}/\d{2}/\d{2}", text):
        return datetime.strptime(text, "%y/%m/%d").replace(tzinfo=KST)
    return None


def _int_or_zero(s: str) -> int:
    s = (s or "").strip().replace(",", "")
    if not s:
        return 0
    # DC sometimes uses 'k' for thousands, but list page usually doesn't.
    m = re.match(r"(\d+)", s)
    return int(m.group(1)) if m else 0


def parse_list(html: str) -> list[PostMeta]:
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
        category = subj_td.get_text(strip=True) if subj_td else ""

        tit_td = tr.select_one("td.gall_tit")
        if tit_td is None:
            continue
        a = tit_td.select_one("a")
        title = a.get_text(strip=True) if a else tit_td.get_text(strip=True)
        href = a.get("href", "") if a else ""
        url = href if href.startswith("http") else f"{BASE}{href}" if href else build_view_url(no)

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
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…(이하 생략)"
    return text


def iter_list_pages(scraper: Scraper, start: int = 1) -> Iterable[tuple[int, list[PostMeta]]]:
    """페이지 1부터 무한히 yield. 호출자가 break 조건으로 끊는다."""
    page = start
    while True:
        url = build_list_url(page)
        html = scraper.fetch(url, referer=BASE + LIST_PATH)
        yield page, parse_list(html)
        page += 1
