"""수집 대상 DC인사이드 갤러리 정의.

갤러리마다 게시판 id, 표시 이름, 말머리(카테고리) 정책, 수집 규모가 다르다.
`--gallery <key>`(CLI) / `?gallery=<key>`(API) 로 선택한다.

파일 네이밍 규칙 (레거시 호환):

- 기본 갤러리(`DEFAULT_GALLERY_KEY`)는 scope 가 없어서 리포트 파일이
  `jgi_daily_YYYY-MM-DD.md`, 캐시가 `cache/days7_YYYY-MM-DD/` 로 유지된다.
- 그 외 갤러리는 scope 접두가 붙는다 → `jgi_tenbagger_daily_YYYY-MM-DD.md`,
  `cache/tenbagger_days7_YYYY-MM-DD/`.

즉 scope=None 은 "예전 버전과 동일한 이름" 이라는 뜻이고, 웹 인덱스는 scope 가
없는 파일을 기본 갤러리 것으로 해석한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 이모지/장식 문자 제거용. 말머리가 `🐕헛소리`, `📢공지` 처럼 이모지로 시작해도
# 같은 카테고리로 인식하게 한다.
_EMOJI_RE = re.compile(
    "["
    "\u2190-\u2bff"  # 화살표/기호 (✔ 등)
    "\u2600-\u27bf"  # 기타 기호
    "\u2b00-\u2bff"
    "\u3030\u303d\u3297\u3299"
    "\ufe0f\u200d\u20e3"  # variation selector / ZWJ / keycap
    "\U0001f000-\U0001faff"
    "\U0001fa70-\U0001faff"
    "]+"
)


def normalize_category(value: str) -> str:
    """말머리 문자열에서 이모지/공백을 제거해 비교 가능한 형태로 만든다."""
    return _EMOJI_RE.sub("", value or "").strip()


@dataclass(frozen=True)
class Gallery:
    key: str
    """CLI/API 에서 쓰는 식별자. 리포트 scope 로도 그대로 사용."""
    gallery_id: str
    """DC인사이드 게시판 id (URL 의 `?id=`)."""
    name: str
    """리포트 제목에 쓰는 정식 이름 (예: 해외주식 갤러리)."""
    short_name: str
    """탭/목록 라벨 (예: 해외주식)."""
    market_label: str
    """공포탐욕 게이지 부제 (예: 코스피·코스닥 시장 심리)."""
    market_hint: str
    """LLM 시스템 프롬프트에 넣는 시장/종목 성격 설명."""
    scope: str | None = None
    """리포트 파일 / 캐시 디렉토리 접두. None 이면 레거시(무접두) 네이밍."""
    include_categories: frozenset[str] | None = None
    """수집할 말머리 (정규화 후 비교). None 이면 제한 없음."""
    exclude_categories: frozenset[str] = frozenset()
    """제외할 말머리 (정규화 후 비교). 공지/광고/설문 등."""
    max_pages: int = 2000
    """스캔 페이지 안전 상한 기본값."""

    @property
    def url(self) -> str:
        return f"https://gall.dcinside.com/mgallery/board/lists/?id={self.gallery_id}"

    @property
    def slug_prefix(self) -> str:
        """리포트 파일 접두 (`jgi` 또는 `jgi_tenbagger`)."""
        return f"jgi_{self.scope}" if self.scope else "jgi"

    def accepts_category(self, category: str) -> bool:
        cat = normalize_category(category)
        if self.include_categories is not None and cat not in self.include_categories:
            return False
        return cat not in self.exclude_categories


KOREAN_STOCK = Gallery(
    key="krstock",
    gallery_id="krstock",
    name="한국주식 갤러리",
    short_name="한국주식",
    market_label="코스피·코스닥 시장 심리",
    market_hint=(
        "국내 증시(코스피/코스닥) 위주. 자주 나오는 예: 삼성전자, SK하이닉스, "
        "카카오, 현대차, 2차전지, 반도체, 금리/환율, 공매도, 배당."
    ),
    scope=None,
    include_categories=frozenset({"일반", "뉴스"}),
    exclude_categories=frozenset({"공지", "AD", "설문"}),
    max_pages=2000,
)

OVERSEAS_STOCK = Gallery(
    key="tenbagger",
    gallery_id="tenbagger",
    name="해외주식 갤러리",
    short_name="해외주식",
    market_label="해외(미국) 시장 심리",
    market_hint=(
        "해외(주로 미국) 증시 위주. 자주 나오는 예: NVDA, TSLA, AAPL, MSFT, "
        "나스닥/S&P500, 연준(FOMC)·금리, 환율, 관세/트럼프, 중국·이란 등 지정학."
    ),
    scope="tenbagger",
    # 해외주식 갤은 말머리가 다양해서(🌎이슈 / 📋분석 / 📈시황 / 💡정보 …)
    # 잡담·광고성 말머리만 제외하고 나머지는 모두 수집한다.
    include_categories=None,
    exclude_categories=frozenset({"공지", "AD", "설문", "헛소리", "졸업장"}),
    # 하루 ~260건(≈6페이지)이라 페이지 상한을 낮게 잡아도 충분하다.
    max_pages=400,
)

GALLERIES: dict[str, Gallery] = {g.key: g for g in (KOREAN_STOCK, OVERSEAS_STOCK)}
DEFAULT_GALLERY_KEY = KOREAN_STOCK.key
DEFAULT_GALLERY = KOREAN_STOCK


def get_gallery(key: str | None) -> Gallery:
    if key is None or not str(key).strip():
        return DEFAULT_GALLERY
    k = str(key).strip().lower()
    if k not in GALLERIES:
        known = ", ".join(GALLERIES)
        raise ValueError(f"알 수 없는 갤러리 '{key}' (사용 가능: {known})")
    return GALLERIES[k]


def resolve_galleries(values: str | None = None) -> list[Gallery]:
    """`"krstock,tenbagger"` → [Gallery, ...].

    `None`/빈 문자열/`"all"` 은 전체 갤러리 (스케줄러 기본값).
    """
    if values is None or not str(values).strip() or str(values).strip().lower() == "all":
        return list(GALLERIES.values())
    keys = [v.strip() for v in str(values).split(",") if v.strip()]
    return [get_gallery(k) for k in keys]


def gallery_for_scope(scope: str | None) -> Gallery:
    """리포트 파일/캐시의 scope 토큰 → Gallery (없으면 기본 갤러리)."""
    if not scope:
        return DEFAULT_GALLERY
    for g in GALLERIES.values():
        if g.scope and g.scope == scope:
            return g
    return DEFAULT_GALLERY
