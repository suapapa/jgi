from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Iterable

from .checkpoint import RunCheckpoint
from .galleries import normalize_category
from .models import Post, PostMeta
from .scraper import KST, ScrapeBlockedError, Scraper, iter_list_pages, parse_view

logger = logging.getLogger(__name__)

# 기본 갤러리(한국주식)의 말머리 정책. 갤러리별 정책은 galleries.py 참고.
DEFAULT_INCLUDE_CATEGORIES = {"일반", "뉴스"}


def calendar_window(target: date) -> tuple[datetime, datetime]:
    """KST 달력 하루 [00:00, 다음날 00:00)."""
    start = datetime(target.year, target.month, target.day, tzinfo=KST)
    return start, start + timedelta(days=1)


def in_window(posted_at: datetime, start: datetime, end: datetime | None) -> bool:
    if posted_at < start:
        return False
    if end is not None and posted_at >= end:
        return False
    return True


def filter_metas_in_window(
    metas: list[PostMeta], start: datetime, end: datetime | None
) -> list[PostMeta]:
    return [m for m in metas if in_window(m.posted_at, start, end)]


def collect_meta_since(
    scraper: Scraper,
    cutoff: datetime,
    *,
    end: datetime | None = None,
    include_categories: Iterable[str] | None = DEFAULT_INCLUDE_CATEGORIES,
    exclude_categories: Iterable[str] | None = (),
    max_pages: int = 2000,
    progress=None,
    checkpoint: RunCheckpoint | None = None,
) -> list[PostMeta]:
    """`cutoff` 시각 이후(및 `end` 미만) 게시글 메타데이터를 페이지 1부터 순회하며 수집.

    `include_categories`가 None이면 말머리 제한 없이 수집하고,
    `exclude_categories`로 공지/광고/잡담 등을 걸러낸다 (이모지 말머리는 정규화 후 비교).

    `checkpoint`가 주어지면 기존 metas.jsonl 을 로드해 dedupe하고,
    `state.json`의 `last_scanned_page` 다음 페이지부터 이어한다.
    """
    include = (
        {normalize_category(c) for c in include_categories}
        if include_categories
        else None
    )
    exclude = {normalize_category(c) for c in exclude_categories} if exclude_categories else set()
    collected: list[PostMeta] = []
    seen_nos: set[int] = set()
    start_page = 1

    if checkpoint is not None:
        for m in checkpoint.iter_metas():
            if in_window(m.posted_at, cutoff, end) and m.no not in seen_nos:
                seen_nos.add(m.no)
                collected.append(m)
        state = checkpoint.load_state()
        last_done = int(state.get("last_scanned_page", 0))
        if last_done > 0:
            # 한 페이지는 다시 스캔 (안전장치: 마지막 페이지가 쓰기 도중 끊겼을 수 있음)
            start_page = last_done
            logger.info(
                "checkpoint 재개: 기존 %d건 로드, 페이지 %d부터 재시작",
                len(collected),
                start_page,
            )

    pages_with_only_old = 0

    for page, posts in iter_list_pages(scraper, start=start_page):
        if page > max_pages:
            logger.warning("max_pages=%d 도달, 수집 중단", max_pages)
            break
        if not posts:
            if page == start_page and not collected:
                # 첫 페이지부터 0건이면 차단/구조 변경을 의심한다 (조용히 빈 리포트 방지).
                raise ScrapeBlockedError(
                    f"페이지 {page}에서 게시글을 찾지 못했습니다 — 차단 또는 페이지 구조 변경 의심"
                )
            logger.info("페이지 %d 게시글 없음, 종료", page)
            break

        page_new: list[PostMeta] = []
        page_old = 0
        for p in posts:
            if p.no in seen_nos:
                continue
            cat = normalize_category(p.category)
            if include is not None and cat not in include:
                continue
            if cat in exclude:
                continue
            if end is not None and p.posted_at >= end:
                continue
            if p.posted_at < cutoff:
                page_old += 1
                continue
            seen_nos.add(p.no)
            page_new.append(p)
            collected.append(p)

        if checkpoint is not None:
            checkpoint.append_metas(page_new)
            checkpoint.save_state(last_scanned_page=page)

        if progress is not None:
            progress(page, len(page_new), len(collected))

        # 한 페이지가 전부 cutoff보다 오래된 글이면 종료
        if not page_new and page_old > 0:
            pages_with_only_old += 1
            if pages_with_only_old >= 2:
                logger.info("2페이지 연속 cutoff 이전만 → 수집 종료")
                if checkpoint is not None:
                    checkpoint.save_state(meta_collection_done=True)
                break
        else:
            pages_with_only_old = 0
    else:
        if checkpoint is not None:
            checkpoint.save_state(meta_collection_done=True)

    return filter_metas_in_window(collected, cutoff, end)


def fetch_bodies(
    scraper: Scraper,
    metas: list[PostMeta],
    *,
    progress=None,
    max_chars: int = 4000,
    checkpoint: RunCheckpoint | None = None,
) -> list[Post]:
    """상위 N개 메타데이터의 본문을 가져와 Post 리스트로 반환.

    `checkpoint`가 주어지면 bodies.jsonl에 이미 있는 글은 재요청하지 않는다.
    """
    cached: dict[int, Post] = checkpoint.load_bodies() if checkpoint else {}
    cached_nos = cached.keys()
    posts: list[Post] = []
    total = len(metas)

    for i, meta in enumerate(metas, 1):
        if meta.no in cached_nos:
            post = cached[meta.no]
            if progress is not None:
                progress(i, total, post, cached=True)
            posts.append(post)
            continue

        url = meta.url or scraper.view_url(meta.no)
        try:
            html = scraper.fetch(url, referer=url)
            body = parse_view(html, max_chars=max_chars)
        except Exception as e:
            logger.warning("본문 가져오기 실패 no=%s: %s", meta.no, e)
            body = ""
        post = Post(**meta.model_dump(), body=body)

        if checkpoint is not None:
            checkpoint.append_body(post)

        posts.append(post)
        if progress is not None:
            progress(i, total, post, cached=False)

    return posts


def default_cutoff(days: int) -> datetime:
    return datetime.now(KST) - timedelta(days=days)
