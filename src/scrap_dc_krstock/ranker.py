from __future__ import annotations

from .models import PostMeta


def score(post: PostMeta, recommend_weight: float = 3.0) -> float:
    return float(post.views) + float(post.recommends) * recommend_weight


def select_top(
    metas: list[PostMeta],
    n: int,
    recommend_weight: float = 3.0,
) -> list[PostMeta]:
    """추천수에 가중치를 두고 조회수와 합산해 상위 N개 선정."""
    if n <= 0:
        return []
    return sorted(metas, key=lambda p: score(p, recommend_weight), reverse=True)[:n]
