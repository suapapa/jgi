from __future__ import annotations

import json
import logging
import os

from openai import OpenAI

from .models import AnalysisResult, Post, PostMeta

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """당신은 한국 주식 커뮤니티(DC인사이드 한국주식 갤러리) 게시글을 분석해\
 시장 민심을 요약하는 분석가입니다. 게시글에는 욕설/은어/풍자가 섞여 있으니 어조에 휘둘리지 말고,\
 다음을 파악하세요:

- 전체 감정 (강세=bullish / 약세=bearish / 중립=neutral / 혼조=mixed)
- 자주 언급된 종목/티커 (예: 삼성전자, SK하이닉스, 카카오, TSLA 등)와 각 종목에 대한 어조
- 핵심 화제 (정책/금리/특정 산업/이벤트 등)
- 인상적이거나 대표적인 의견 (간결한 인용)
- 투자자들이 걱정하는 리스크

응답은 반드시 지정된 JSON 스키마를 따르고, 한국어로 작성하세요."""


_RESULT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_sentiment": {
            "type": "string",
            "enum": ["bullish", "bearish", "neutral", "mixed"],
        },
        "sentiment_breakdown": {
            "type": "object",
            "properties": {
                "bullish": {"type": "number"},
                "bearish": {"type": "number"},
                "neutral": {"type": "number"},
            },
            "required": ["bullish", "bearish", "neutral"],
        },
        "hot_tickers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "mentions": {"type": "integer"},
                    "sentiment": {
                        "type": "string",
                        "enum": ["bullish", "bearish", "neutral", "mixed"],
                    },
                },
                "required": ["ticker", "mentions", "sentiment"],
            },
        },
        "key_themes": {"type": "array", "items": {"type": "string"}},
        "notable_quotes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "title": {"type": "string"},
                    "views": {"type": "integer"},
                    "recommends": {"type": "integer"},
                },
                "required": ["quote"],
            },
        },
        "risks": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": [
        "overall_sentiment",
        "sentiment_breakdown",
        "hot_tickers",
        "key_themes",
        "notable_quotes",
        "risks",
        "summary",
    ],
}


class Analyzer:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        self.model = model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _build_user_prompt(
        self,
        all_metas: list[PostMeta],
        top_posts: list[Post],
        meta_sample_size: int = 200,
    ) -> str:
        # 메타 통계
        total = len(all_metas)
        total_views = sum(m.views for m in all_metas)
        total_rec = sum(m.recommends for m in all_metas)
        total_cmt = sum(m.comments for m in all_metas)
        by_cat: dict[str, int] = {}
        for m in all_metas:
            by_cat[m.category] = by_cat.get(m.category, 0) + 1
        cat_line = ", ".join(f"{k} {v}건" for k, v in sorted(by_cat.items(), key=lambda x: -x[1]))

        # 한국주식 갤러리는 글이 매우 많아서 전체를 그대로 못 넣는다.
        # 추천 상위 + 조회 상위 + 댓글 상위를 골고루 sampling.
        if total > meta_sample_size:
            by_rec = sorted(all_metas, key=lambda m: m.recommends, reverse=True)[: meta_sample_size // 3]
            by_view = sorted(all_metas, key=lambda m: m.views, reverse=True)[: meta_sample_size // 3]
            by_cmt = sorted(all_metas, key=lambda m: m.comments, reverse=True)[: meta_sample_size // 3]
            seen: set[int] = set()
            sample: list[PostMeta] = []
            for src in (by_rec, by_view, by_cmt):
                for m in src:
                    if m.no in seen:
                        continue
                    seen.add(m.no)
                    sample.append(m)
            sample_note = (
                f"(전체 {total}건 중 추천/조회/댓글 상위 합집합 {len(sample)}건 샘플)"
            )
        else:
            sample = list(all_metas)
            sample_note = f"(전체 {total}건)"

        meta_lines = [
            f"- [{m.category}] {m.title} | 조회 {m.views} · 추천 {m.recommends} · 댓글 {m.comments}"
            for m in sample
        ]
        meta_block = "\n".join(meta_lines)

        # 본문이 있는 상위 글
        body_blocks = []
        for i, p in enumerate(top_posts, 1):
            if not p.body:
                continue
            body_blocks.append(
                f"### {i}. {p.title}\n"
                f"- 작성자: {p.author}\n"
                f"- 작성: {p.posted_at.isoformat()}\n"
                f"- 조회 {p.views}, 추천 {p.recommends}, 댓글 {p.comments}\n\n"
                f"{p.body}"
            )
        body_block = "\n\n---\n\n".join(body_blocks)

        return f"""# 분석 대상

## 통계
- 수집 기간 게시글 수: {total}건
- 누적 조회: {total_views:,} · 누적 추천: {total_rec:,} · 누적 댓글: {total_cmt:,}
- 카테고리 분포: {cat_line}

## 게시글 제목 샘플 {sample_note}
{meta_block}

## 조회수/추천수 상위 본문 (총 {len(top_posts)}건)
{body_block}

---

위 데이터를 바탕으로 한국 주식 시장에 대한 커뮤니티 민심을 분석하고, 지정된 JSON 형식으로 응답하세요. 응답은 JSON 객체 하나여야 합니다."""

    def analyze(self, all_metas: list[PostMeta], top_posts: list[Post]) -> AnalysisResult:
        user_prompt = self._build_user_prompt(all_metas, top_posts)
        logger.info(
            "LLM 호출: model=%s, metas=%d, bodies=%d, prompt_chars=%d",
            self.model,
            len(all_metas),
            len(top_posts),
            len(user_prompt),
        )

        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        # JSON 모드: OpenAI 호환 서버 중 일부만 지원하므로 실패 시 일반 텍스트로 폴백.
        try:
            resp = self.client.chat.completions.create(
                **kwargs,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.warning("response_format=json_object 미지원으로 추정, 일반 호출로 폴백: %s", e)
            resp = self.client.chat.completions.create(**kwargs)

        content = resp.choices[0].message.content or ""
        data = _extract_json(content)
        return AnalysisResult.model_validate(data)


def _extract_json(text: str) -> dict:
    """LLM이 가끔 ```json``` 블록이나 앞뒤 설명을 붙이는 경우 JSON 객체만 뽑아낸다."""
    text = text.strip()
    # 직접 시도
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ```json ... ``` 블록 추출
    import re

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))

    # 첫 { 부터 마지막 } 까지
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError(f"LLM 응답에서 JSON을 찾지 못함: {text[:300]}")
