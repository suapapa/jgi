# JGI — JooGall Sentiment Index

DC인사이드 주식 갤러리의 지난 일주일치 게시글을 수집해, OpenAI 호환 LLM으로 시장 민심을 요약한 마크다운 리포트를 생성합니다. 갤러리별로 **탭**을 나눠 웹에서 열람합니다.

| 갤러리 (`--gallery`) | 게시판 | 성격 |
|---|---|---|
| `krstock` (기본) | [한국주식 갤러리](https://gall.dcinside.com/mgallery/board/lists/?id=krstock) | 국내(코스피/코스닥) — 하루 ~1만 건 |
| `tenbagger` | [해외주식 갤러리](https://gall.dcinside.com/mgallery/board/lists/?id=tenbagger) | 해외(미국) — 하루 ~260건 |

## 동작 방식

1. 목록 페이지를 순회하며 일주일치 게시글 **메타데이터**(번호/제목/작성자/작성일/조회/추천)를 전부 수집
2. 조회수 + (추천수 × 가중치) 기준 **상위 N개**만 상세 페이지 본문을 크롤링
3. 메타데이터 전체 + 상위 N개 본문을 LLM에 보내 종합 감정·화제 종목·주요 화제·우려를 요약
4. `reports/jgi_YYYY-MM-DD_to_YYYY-MM-DD.md` 로 저장 (갤러리별 파일 이름 규칙은 아래 참고)

## 설치

```bash
uv sync
cp .env.example .env
# .env 편집해서 OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL 채우기
```

## 사용

```bash
# 기본 (한국주식 갤, 7일치, 상위 30개 본문)
uv run jgi

# 갤러리 지정
uv run jgi --gallery tenbagger          # 해외주식 갤
uv run jgi --gallery krstock,tenbagger  # 둘 다 순서대로
uv run jgi --gallery all                # 전체

# 옵션 지정
uv run jgi --days 7 --top 30 --output reports/

# LLM 호출 없이 수집만 (디버깅)
uv run jgi --dry-run

# 모델 override
uv run jgi --model gpt-4o
```

## 환경 변수

| 이름 | 기본 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI 호환 API 키 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API 엔드포인트 (로컬 LLM/타 서비스 사용 시 변경) |
| `OPENAI_MODEL` | `gpt-4o-mini` | 사용할 모델 이름 |
| `GALLERIES` | 전체 | `jgi-serve` 스케줄러가 매일 생성할 갤러리 (예: `krstock,tenbagger`) |

## 옵션

- `--gallery KEY[,KEY...]` 수집할 갤러리 (`krstock` 기본, `tenbagger`). 쉼표로 여러 개 지정 가능
- `--days N` 일주일 → N일치 (기본 7)
- `--date YYYY-MM-DD` KST 달력 하루 (00:00~23:59). 지정 시 `--days` 무시
- `--force` 기존 리포트 파일이 있어도 다시 생성
- `--top N` 본문 크롤링할 상위 게시글 수 (기본 30)
- `--output DIR` 리포트 출력 디렉토리 (기본 `reports/`)
- `--model NAME` 모델 override
- `--dry-run` LLM 호출 생략, 수집/랭킹 결과만 JSON으로 저장
- `--recommend-weight F` 랭킹 점수에서 추천수 가중치 (기본 3.0)
- `--cache-dir DIR` 체크포인트 저장 디렉토리 (기본 `cache/`)
- `--fresh` 기존 체크포인트 무시하고 처음부터 다시 수집
- `--refresh-analysis` 수집/본문 캐시는 유지하고 LLM 분석만 다시 수행

## 리포트 파일 이름 / 캐시 레이아웃

기본 갤러리(`krstock`)는 예전 이름을 그대로 쓰고, 나머지 갤러리는 key 접두가 붙습니다.

| 갤러리 | 리포트 | 캐시 디렉토리 |
|---|---|---|
| `krstock` | `jgi_daily_2026-09-27.md` · `jgi_2026-09-01_to_2026-09-07.md` | `cache/days7_2026-09-27/` |
| `tenbagger` | `jgi_tenbagger_daily_2026-09-27.md` · `jgi_tenbagger_2026-09-01_to_2026-09-07.md` | `cache/tenbagger_days7_2026-09-27/` |

웹 목록은 접두가 없으면 기본 갤러리 것으로 보고, 무접두 구버전(`krstock_*.md`)도 함께 읽습니다.

## 단계별 자동 재개

세 단계 (① 메타 수집 → ② 본문 크롤링 → ③ LLM 분석) 모두 캐시 디렉토리 아래에 점진적으로 저장됩니다.

```
cache/days7_2026-05-16/
├── state.json        # last_scanned_page, meta_collection_done
├── metas.jsonl       # 페이지마다 append-only
├── bodies.jsonl      # 본문마다 append-only
└── analysis.json     # LLM 결과
```

중간에 실패하면 **같은 날짜 + 같은 `--days`로 다시 실행**하기만 하면 자동으로 이어합니다:

- 메타 수집 도중 멈춤 → 마지막으로 스캔한 페이지부터 재개
- 본문 크롤링 도중 멈춤 → 이미 받은 본문은 스킵
- LLM 분석 실패 → 메타/본문은 그대로 두고 LLM만 다시
- 리포트만 다시 생성 → 그냥 또 실행 (캐시된 결과 사용)

처음부터 다시 하려면:

```bash
uv run jgi --days 7 --fresh         # 전체 다시
uv run jgi --days 7 --refresh-analysis  # LLM만 다시
```

## 주의

- 한국주식 갤러리는 매우 활발해 **하루 약 1만 건**의 글이 올라옵니다.
  - 7일치 전체 메타데이터 수집은 ~1,400페이지를 거치며 **약 15~25분** 소요됩니다.
  - `--days 1` 또는 `--days 2` 정도로 먼저 검증하기를 권장합니다.
- 해외주식 갤러리는 하루 ~260건(~6페이지)이라 7일치도 몇 분 안에 끝납니다.
- 말머리(카테고리) 정책은 갤러리마다 다릅니다 (`src/jgi/galleries.py`):
  - `krstock`: `일반`, `뉴스`만 수집
  - `tenbagger`: `공지`/`AD`/`설문`/`헛소리`/`졸업장`만 제외하고 나머지 모두 수집 (🌎이슈, 📋분석, 📈시황, 💡정보 …)
- LLM에 보내는 프롬프트는 자동 압축됩니다 — 전체 메타데이터 통계 + 추천/조회/댓글 상위 합집합 ~200건 제목 + 본문 상위 N건.
- DC인사이드에 적절한 딜레이를 두고 요청합니다. 차단 시:
  - **차단 감지**: DC는 차단할 때 상태코드 대신 **빈 본문(200, 0자)** 을 돌려줍니다. 예전에는 이걸 "게시글 없음"으로 받아들여 수집이 조용히 끝나고 **잘린 리포트**가 만들어졌습니다. 지금은 빈 응답을 차단으로 보고 재시도(5회)한 뒤 `ScrapeBlockedError`로 실패시킵니다 (첫 페이지 0건도 동일).
  - 실패하면 몇 분~수십 분 기다렸다가 **같은 캐시로 재실행**하세요. 이미 받은 메타/본문은 재사용하고 이어서 수집합니다.
  - `--min-delay`, `--max-delay`를 늘리거나
  - User-Agent를 추가하거나
  - `cloudscraper` 의존성을 추가해 fallback 구성하세요.
- 갤러리 하나가 차단/실패해도 스케줄러는 다음 갤러리를 계속 진행하고, 실패는 `/api/status`의 `last_error`에 남습니다.

## 일일 리포트 + 웹 열람

전날(KST 00:00~23:59) 달력 하루치를 수집해 리포트를 만들고, 브라우저에서 갤러리 탭(한국주식/해외주식)으로 나눠 읽을 수 있습니다.

```bash
# 달력 하루 (수동, 갤러리 지정)
uv run jgi --gallery tenbagger --date 2026-09-27 --top 30

# 프론트 빌드 (최초 1회)
cd web && npm install && npm run build && cd ..

# 프론트 스모크 테스트 (선택: jsdom으로 탭/게이지 검증, 네트워크 불필요)
cd web && npm i --no-save jsdom && node uitest.cjs

# API + 스케줄러 + 웹 UI (기본 매일 07:00 KST에 전날 리포트 생성, GALLERIES 전체)
uv run jgi-serve
# → http://127.0.0.1:8080            (한국주식 탭)
# → http://127.0.0.1:8080/?gallery=tenbagger  (해외주식 탭)

# VPS (Docker)
docker compose up -d --build
```

환경 변수(`.env`): `WEB_USERNAME` / `WEB_PASSWORD`를 설정하면 전체 사이트에 HTTP Basic 인증이 적용됩니다. `SCHEDULE_CRON`으로 스케줄을 바꿀 수 있습니다 (기본 `0 7 * * *`). `GALLERIES=krstock,tenbagger`로 매일 생성할 갤러리를 고릅니다.

수동 재생성:

```bash
# 두 갤러리 모두
curl -u user:pass -X POST http://localhost:8080/api/jobs \
  -H 'Content-Type: application/json' -d '{"date":"2026-09-27","force":true}'

# 특정 갤러리만
curl -u user:pass -X POST http://localhost:8080/api/jobs \
  -H 'Content-Type: application/json' -d '{"date":"2026-09-27","gallery":"tenbagger","force":true}'
```

웹 API: `GET /api/galleries` (탭 목록), `GET /api/reports[?gallery=KEY]`, `GET /api/reports/{slug}/json`, `GET /api/status`.

## 예시 워크플로우

```bash
# 0) 빠른 검증 (LLM 호출 없이 갤러리별 몇 페이지만)
uv run jgi --gallery tenbagger --days 1 --top 3 --max-pages 3 --dry-run

# 1) 2일치로 LLM 분석까지 가볍게 (~5분)
uv run jgi --days 2 --top 20

# 2) 본 실행 (7일치, ~20분)
uv run jgi --days 7 --top 30
```
