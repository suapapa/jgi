# scrap-dc-krstock

DC인사이드 [한국주식 갤러리](https://gall.dcinside.com/mgallery/board/lists/?id=krstock)의 지난 일주일치 게시글을 수집해, OpenAI 호환 LLM으로 시장 민심을 요약한 마크다운 리포트를 생성합니다.

## 동작 방식

1. 목록 페이지를 순회하며 일주일치 게시글 **메타데이터**(번호/제목/작성자/작성일/조회/추천)를 전부 수집
2. 조회수 + (추천수 × 가중치) 기준 **상위 N개**만 상세 페이지 본문을 크롤링
3. 메타데이터 전체 + 상위 N개 본문을 LLM에 보내 종합 감정·화제 종목·주요 화제·우려를 요약
4. `reports/krstock_YYYY-MM-DD_to_YYYY-MM-DD.md` 로 저장

## 설치

```bash
uv sync
cp .env.example .env
# .env 편집해서 OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL 채우기
```

## 사용

```bash
# 기본 (7일치, 상위 30개 본문)
uv run scrap-dc-krstock

# 옵션 지정
uv run scrap-dc-krstock --days 7 --top 30 --output reports/

# LLM 호출 없이 수집만 (디버깅)
uv run scrap-dc-krstock --dry-run

# 모델 override
uv run scrap-dc-krstock --model gpt-4o
```

## 환경 변수

| 이름 | 기본 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI 호환 API 키 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API 엔드포인트 (로컬 LLM/타 서비스 사용 시 변경) |
| `OPENAI_MODEL` | `gpt-4o-mini` | 사용할 모델 이름 |

## 옵션

- `--days N` 일주일 → N일치 (기본 7)
- `--top N` 본문 크롤링할 상위 게시글 수 (기본 30)
- `--output DIR` 리포트 출력 디렉토리 (기본 `reports/`)
- `--model NAME` 모델 override
- `--dry-run` LLM 호출 생략, 수집/랭킹 결과만 JSON으로 저장
- `--recommend-weight F` 랭킹 점수에서 추천수 가중치 (기본 3.0)

## 주의

- 한국주식 갤러리는 매우 활발해 **하루 약 1만 건**의 글이 올라옵니다.
  - 7일치 전체 메타데이터 수집은 ~1,400페이지를 거치며 **약 15~25분** 소요됩니다.
  - `--days 1` 또는 `--days 2` 정도로 먼저 검증하기를 권장합니다.
- LLM에 보내는 프롬프트는 자동 압축됩니다 — 전체 메타데이터 통계 + 추천/조회/댓글 상위 합집합 ~200건 제목 + 본문 상위 N건.
- DC인사이드에 적절한 딜레이를 두고 요청합니다. 차단 시:
  - `--min-delay`, `--max-delay`를 늘리거나
  - User-Agent를 추가하거나
  - `cloudscraper` 의존성을 추가해 fallback 구성하세요.

## 예시 워크플로우

```bash
# 0) 빠른 검증 (LLM 호출 없이 1일치만)
uv run scrap-dc-krstock --days 1 --top 3 --dry-run

# 1) 2일치로 LLM 분석까지 가볍게 (~5분)
uv run scrap-dc-krstock --days 2 --top 20

# 2) 본 실행 (7일치, ~20분)
uv run scrap-dc-krstock --days 7 --top 30
```
