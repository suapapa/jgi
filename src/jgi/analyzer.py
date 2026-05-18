from __future__ import annotations

import heapq
import json
import logging
import os
import re
from collections import Counter

from openai import OpenAI
from pydantic import ValidationError

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

매우 중요한 출력 규칙:
1. 응답은 반드시 JSON 객체 하나여야 한다. 마크다운/설명/코드블록 금지.
2. JSON의 **키 이름은 반드시 영어**로 아래 명세된 그대로 사용한다. 한국어 키 금지.
   (예: "overall_sentiment" O, "전체_감정" X / "분석_요약" X)
3. **값(value)** 중 자유 텍스트(요약, 인용, 화제, 리스크 등)는 한국어로 작성한다.
4. enum 값("bullish"/"bearish"/"neutral"/"mixed")은 영어 그대로 사용한다.

필수 JSON 스키마 (모든 키 필수):
{
  "overall_sentiment": "bullish" | "bearish" | "neutral" | "mixed",
  "sentiment_breakdown": {
    "bullish": <0~1 사이 실수>,
    "bearish": <0~1 사이 실수>,
    "neutral": <0~1 사이 실수>
  },
  "hot_tickers": [
    {"ticker": "<종목명>", "mentions": <정수>, "sentiment": "bullish|bearish|neutral|mixed"}
  ],
  "key_themes": ["<핵심 화제 한국어>", ...],
  "notable_quotes": [
    {"quote": "<인용 한국어>", "title": "<게시글 제목>", "views": <정수>, "recommends": <정수>}
  ],
  "risks": ["<리스크 한국어>", ...],
  "summary": "<전반 민심 요약 한국어, 3~6문장>"
}"""


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
        total_views = 0
        total_rec = 0
        total_cmt = 0
        by_cat: Counter[str] = Counter()
        for m in all_metas:
            total_views += m.views
            total_rec += m.recommends
            total_cmt += m.comments
            by_cat[m.category] += 1
        cat_line = ", ".join(f"{k} {v}건" for k, v in by_cat.most_common())

        # 한국주식 갤러리는 글이 매우 많아서 전체를 그대로 못 넣는다.
        # 추천 상위 + 조회 상위 + 댓글 상위를 골고루 sampling.
        if total > meta_sample_size:
            third = meta_sample_size // 3
            by_rec = heapq.nlargest(third, all_metas, key=lambda m: m.recommends)
            by_view = heapq.nlargest(third, all_metas, key=lambda m: m.views)
            by_cmt = heapq.nlargest(third, all_metas, key=lambda m: m.comments)
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

위 데이터를 바탕으로 한국 주식 시장에 대한 커뮤니티 민심을 분석하고, 시스템 메시지에 명시된 JSON 스키마대로 응답하세요.

규칙 재확인:
- 출력은 JSON 객체 **하나만**. 앞뒤 설명/마크다운/```json 금지.
- 최상위 키는 정확히: overall_sentiment, sentiment_breakdown, hot_tickers, key_themes, notable_quotes, risks, summary
- 키를 한국어로 번역하지 말 것. 값(설명문)은 한국어로 쓸 것."""

    def analyze(self, all_metas: list[PostMeta], top_posts: list[Post]) -> AnalysisResult:
        user_prompt = self._build_user_prompt(all_metas, top_posts)
        logger.info(
            "LLM 호출: model=%s, metas=%d, bodies=%d, prompt_chars=%d",
            self.model,
            len(all_metas),
            len(top_posts),
            len(user_prompt),
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        content = self._call(messages)
        data = _extract_json(content)

        try:
            return AnalysisResult.model_validate(data)
        except ValidationError as e:
            logger.warning(
                "1차 응답이 스키마와 불일치. 키 정정 재요청. 받은 최상위 키=%s, 오류=%s",
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                e.errors()[:3],
            )
            correction = (
                "직전 응답의 JSON 키가 스키마와 다릅니다. 다시 보내세요.\n"
                "최상위 키는 정확히 다음 영문 키만 사용: "
                "overall_sentiment, sentiment_breakdown, hot_tickers, key_themes, "
                "notable_quotes, risks, summary.\n"
                "값(설명문)은 한국어로 작성하되, **키는 절대 한국어로 번역하지 마세요.**\n"
                "직전에 보낸 내용:\n" + content[:2000]
            )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": correction})
            content2 = self._call(messages)
            data2 = _extract_json(content2)
            try:
                return AnalysisResult.model_validate(data2)
            except ValidationError:
                logger.error("재시도 후에도 스키마 불일치. 원본 응답: %s", content2[:1000])
                raise

    def _call(self, messages: list[dict]) -> str:
        kwargs = dict(
            model=self.model,
            messages=messages,
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
        return resp.choices[0].message.content or ""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> dict:
    """LLM이 가끔 ```json``` 블록이나 앞뒤 설명을 붙이는 경우 JSON 객체만 뽑아낸다."""
    text = text.strip()
    # 직접 시도
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ```json ... ``` 블록 추출
    m = _JSON_FENCE_RE.search(text)
    if m:
        return json.loads(m.group(1))

    # 첫 { 부터 마지막 } 까지
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError(f"LLM 응답에서 JSON을 찾지 못함: {text[:300]}")
