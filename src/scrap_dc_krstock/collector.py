from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

from .models import Post, PostMeta
from .scraper import KST, Scraper, build_view_url, iter_list_pages, parse_view

logger = logging.getLogger(__name__)

# 일반 갤러리에서 분석에 의미 있는 카테고리만 남긴다.
DEFAULT_INCLUDE_CATEGORIES = {"일반", "뉴스"}


def collect_meta_since(
    scraper: Scraper,
    cutoff: datetime,
    *,
    include_categories: Iterable[str] = DEFAULT_INCLUDE_CATEGORIES,
    max_pages: int = 200,
    progress=None,
) -> list[PostMeta]:
    """`cutoff` 시각 이후의 게시글 메타데이터를 페이지 1부터 순회하며 수집."""
    include = set(include_categories) if include_categories else None
    collected: list[PostMeta] = []
    seen_nos: set[int] = set()
    pages_with_only_old = 0

    for page, posts in iter_list_pages(scraper):
        if page > max_pages:
            logger.warning("max_pages=%d 도달, 수집 중단", max_pages)
            break
        if not posts:
            logger.info("페이지 %d 게시글 없음, 종료", page)
            break

        page_new = 0
        page_old = 0
        for p in posts:
            if p.no in seen_nos:
                continue
            if include is not None and p.category not in include:
                continue
            if p.posted_at < cutoff:
                page_old += 1
                continue
            seen_nos.add(p.no)
            collected.append(p)
            page_new += 1

        if progress is not None:
            progress(page, page_new, len(collected))

        # 한 페이지가 전부 cutoff보다 오래된 글이면 종료
        if page_new == 0 and page_old > 0:
            pages_with_only_old += 1
            if pages_with_only_old >= 2:
                logger.info("2페이지 연속 cutoff 이전만 → 수집 종료")
                break
        else:
            pages_with_only_old = 0

    return collected


def fetch_bodies(
    scraper: Scraper,
    metas: list[PostMeta],
    *,
    progress=None,
    max_chars: int = 4000,
) -> list[Post]:
    """상위 N개 메타데이터의 본문을 가져와 Post 리스트로 반환."""
    posts: list[Post] = []
    for i, meta in enumerate(metas, 1):
        url = meta.url or build_view_url(meta.no)
        try:
            html = scraper.fetch(url, referer=url)
            body = parse_view(html, max_chars=max_chars)
        except Exception as e:
            logger.warning("본문 가져오기 실패 no=%s: %s", meta.no, e)
            body = ""
        post = Post(**meta.model_dump(), body=body)
        posts.append(post)
        if progress is not None:
            progress(i, len(metas), post)
    return posts


def default_cutoff(days: int) -> datetime:
    return datetime.now(KST) - timedelta(days=days)
