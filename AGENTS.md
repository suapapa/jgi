# AGENTS.md

다른 AI 에이전트가 이 저장소에서 작업할 때 참고할 핵심 컨텍스트. README는 사용자용, AGENTS는 작업자용.

## 한 줄 요약

**JGI (JooGall Sentiment Index)** — DC인사이드 **주식 갤러리**(한국주식 갤 `krstock` / 해외주식 갤 `tenbagger`)의 일정 기간 게시글을 수집해 OpenAI 호환 LLM으로 시장 민심을 요약하는 Python CLI + 웹 뷰어(갤러리 탭).

## 파이프라인 (3단계 + 리포트)

```
1) 메타 수집      → metas.jsonl  (페이지마다 append)
2) 본문 크롤링    → bodies.jsonl (글마다 append)
3) LLM 분석       → analysis.json
4) 마크다운 리포트 → reports/jgi_...md  → 웹 탭에서 열람
```

각 단계는 `RunCheckpoint`에 점진적으로 저장되어 **중간 실패 시 자동 재개**됨. 같은 날짜 + 같은 `--days`이면 캐시 디렉토리가 동일하므로 그냥 재실행하면 이어한다.

## 갤러리 추상화 (중요)

- **`src/jgi/galleries.py` 가 단일 진실 공급원.** `Gallery(key, gallery_id, name, short_name, market_label, market_hint, scope, include_categories, exclude_categories, max_pages)`.
  - `krstock` — scope=None(레거시 이름 유지), include `{일반, 뉴스}`, max_pages 2000
  - `tenbagger` — scope="tenbagger"(접두 붙음), exclude `{공지, AD, 설문, 헛소리, 졸업장}`, max_pages 400
- 선택 경로: CLI `--gallery krstock,tenbagger|all` → `resolve_galleries()`, API `?gallery=`, 스케줄러 `GALLERIES` env, 리포트/캐시의 scope 접두 → `gallery_for_scope()`.
- **이름 규칙 (깨면 기존 데이터와 섞인다)**:
  | 갤러리 | 리포트 | 캐시 |
  |---|---|---|
  | 기본(krstock) | `jgi_daily_*.md`, `jgi_*_to_*.md` | `cache/days7_*/`, `cache/cal_*/` |
  | 그 외 | `jgi_{scope}_daily_*.md` | `cache/{scope}_days7_*/`, `cache/{scope}_cal_*/` |
  `reports_index.py` 정규식이 선택적 `_(?P<scope>[a-z0-9]+)` 그룹으로 둘 다 읽고, scope가 없으면 기본 갤러리로 해석한다. 구 `krstock_*.md`도 계속 읽음.
- **CLI `--gallery` 기본값은 krstock 하나** (인자 없이 `uv run jgi`가 두 갤러리를 돌게 만들지 말 것). 전체는 `--gallery all` / 스케줄러 `GALLERIES` env(미설정 = 전체).
- 새 갤러리 추가 = `galleries.py`에 `Gallery(...)` 한 개. 파이프라인/웹/CLI는 수정 불필요.
- 말머리 비교는 **이모지 제거 후**(`normalize_category`) 수행. `include_categories=None` + exclude 조합도 지원.

## 디렉토리 / 진입점

- `src/jgi/galleries.py` — 갤러리 정의 + 말머리 정규화 (여기부터 볼 것)
- `src/jgi/cli.py:main` — argparse → 갤러리 루프 → 4단계 오케스트레이션 (체크포인트 wiring 포함)
- `src/jgi/scraper.py` — `Scraper` 클래스(httpx + tenacity 재시도, `gallery_id` 보유 / `list_url`·`view_url`), `parse_list`, `parse_view`
- `src/jgi/collector.py` — `collect_meta_since`(include/exclude 말머리), `fetch_bodies` (둘 다 `checkpoint=` 옵션 지원)
- `src/jgi/ranker.py` — `select_top` (조회수 + 추천수×가중치)
- `src/jgi/analyzer.py` — `Analyzer` (OpenAI 호환 클라이언트, base_url 설정 가능, 갤러리별 시스템 프롬프트 `build_system_prompt`)
- `src/jgi/reporter.py` — 마크다운 렌더 (제목에 갤러리 이름, `scope` 접두 파일명)
- `src/jgi/checkpoint.py` — `RunCheckpoint` (jsonl append-only 저장, `scope` 접두)
- `src/jgi/models.py` — `PostMeta`, `Post`, `AnalysisResult` (pydantic)
- `src/jgi/web/app.py` — FastAPI (`/api/galleries`, `/api/reports[?gallery=]`, `/api/reports/{slug}/json`, `/api/jobs`)
- `src/jgi/web/scheduler.py` — `configured_galleries()` 를 순회하며 일일 리포트 생성 (한 갤러리 실패가 다음 갤러리를 막지 않음)
- `web/src/main.ts` — SPA: `?gallery=` 쿼리로 탭 전환, 탭 개수는 `/api/reports` 전체에서 집계
- `web/uitest.cjs` — 빌드 산출물을 jsdom으로 검증하는 프론트 스모크 테스트 (`npm i --no-save jsdom && node uitest.cjs`)

CLI: `jgi` (수집·분석), `jgi-serve` (웹 UI + 스케줄러)

## 도메인 지식 (놓치기 쉬운 사실)

- **글이 매우 많다**: 한국주식 갤러리는 **하루 약 9,700건**(1728건/44페이지 실측 예시). 7일치는 ~7만 건. 해외주식 갤은 **하루 ~260건(≈6페이지)**. 그래서:
  - 메타데이터는 전체 수집하지만 LLM에는 **샘플(추천/조회/댓글 상위 합집합 ~200건)**만 보냄 → `Analyzer._build_user_prompt` 참고.
  - 한국주식 7일치 풀 수집은 ~15–25분. `--days 1~2`로 먼저 검증할 것. 해외주식은 7일치도 몇 분.
- **DC 페이지 구조 (재확인은 필요할 때만)**:
  - 목록: `table.gall_list tbody tr.ub-content` — 공지/AD/설문은 `td.gall_num`이 `-`라 스킵.
  - **말머리(`td.gall_subject`)**: 셀 폭이 좁으면 **잘린 텍스트**만 넣고 원본은 툴팁 `p.subject_inner#head_txt_org_*`에 담는다
    (`🐕헛소` + `🐕헛소리`). → 툴팁 텍스트를 **우선 사용**해야 한다. td 전체 텍스트를 쓰면 카테고리가 어긋나 필터가 뚫린다.
  - 날짜: `td.gall_date`의 `title="2026-05-15 20:47:49"`를 그대로 KST로 파싱. 폴백으로 `HH:MM` / `YY.MM.DD`.
  - 본문: `.write_div` (또는 `.writing_view_box`). **텍스트 0자는 종종 정상**(이미지만 있는 글) — 파싱 실패로 단정하지 말 것.
  - URL: `/mgallery/board/view/?id=<gallery_id>&no=<N>`
- **anti-bot (중요)**: `httpx` + UA rotation + `Referer` + 딜레이로 평소엔 통과하지만, 같은 IP에서 수십 페이지를 연속으로 긁으면 차단된다.
  - **차단 신호는 상태코드가 아니라 빈 본문(200, 0자)** 이다. 정상 응답으로 받아들이면 "게시글 없음"으로 수집이 조용히 끝나 **잘린 리포트**가 만들어진다.
  - 그래서 `Scraper.fetch`가 `MIN_HTML_CHARS` 미만이면 `ScrapeBlockedError`로 재시도(5회) 후 실패시키고, `collect_meta_since`도 첫 페이지 0건이면 실패시킨다. **이 가드를 약화시키지 말 것.**
  - 차단되면 몇 분~수십 분 기다렸다가 같은 캐시로 재실행(이어서 수집). `cloudscraper` 도입은 미적용 (README 참고).

## 재개 모델 (중요)

- 캐시 키: `cache/[<scope>_]days{N}_{YYYY-MM-DD}/` — `RunCheckpoint(cache_dir, days, scope=…)`에서 `date.today()` 사용. 갤러리별로 접두가 붙어 서로 섞이지 않는다.
- `state.json`의 `last_scanned_page`부터 한 페이지 재스캔하여 안전 보강 (마지막 페이지 쓰기 도중 끊김 대비).
- `metas.jsonl` / `bodies.jsonl`은 append-only이므로 dedupe는 메모리에서 `no` 기준 set으로 수행.
- 날짜가 바뀌면 cutoff도 바뀌어 새 디렉토리가 됨 → 의도된 동작.
- `--fresh` = `checkpoint.reset()`, `--refresh-analysis` = `checkpoint.reset_analysis()`.
- 실행 락은 **갤러리별** `cache/.run_{key}.lock` (갤러리끼리는 병렬 실행 가능, 같은 갤러리 중복 실행은 차단).

## LLM 출력 규약

`AnalysisResult` 스키마(영문 키, 한국어 값). 시스템 프롬프트에 명시되어 있고 `Analyzer.analyze`가 `response_format=json_object`를 우선 시도하고 실패하면 텍스트로 폴백한 뒤 `_extract_json`으로 JSON 블록을 추출함. base_url이 OpenAI가 아닌 호환 서비스인 경우 `response_format` 미지원이 흔하니 폴백 경로를 유지할 것.

프롬프트는 `SYSTEM_PROMPT_TEMPLATE`(=`string.Template`) + `build_system_prompt(gallery)` 로 **갤러리별 치환**한다. JSON 스키마에 중괄호가 많으므로 `str.format()` 으로 되돌리지 말 것(`KeyError` 발생) — `$name` 치환 또는 이중 중괄호 이스케이프를 유지.

## 작업 시 주의

- **새 컬렉터 옵션 추가**: `cli.py`에서 argparse → `collect_meta_since` / `fetch_bodies`로 전달. checkpoint 인자는 그대로 통과시킬 것.
- **갤러리별 정책 변경**: 말머리/페이지 상한은 `galleries.py`만 고치고 파이프라인에 하드코딩하지 말 것.
- **모델 변경**: `models.py`의 pydantic 모델은 jsonl 직렬화 호환성에 영향 → 필드 추가는 기본값을 줘야 기존 캐시 로드 가능.
- **`max_pages` 기본값**: 갤러리별 (`krstock` 2,000 = 7일치 ~1,400페이지 + 여유, `tenbagger` 400). 낮추지 말 것.
- **딜레이**: 0.4–0.9초가 현재 안전선. 더 줄이면 차단 위험.
- **모바일 URL**: `m.dcinside.com/board/krstock` → 데스크탑으로 301 리다이렉트. 분기시키지 말 것.
- **댓글**: 현재 스코프 밖. 모델에 `comments` 카운트만 들어있고 본문은 댓글 미포함.
- **리포트 파일명**: 접두 규칙은 위 표 참고. `report_filename(..., scope=…)` 한 곳에서만 만든다.
- **웹 탭**: 탭은 버튼이 아니라 링크(`/?gallery=<key>`) — 활성 탭이 항상 URL에 있어야 한다. 탭 목록은 `/api/galleries`(스케줄러 `GALLERIES` 기준)에서 온다.

## 동작 확인 (스모크)

```bash
# 캐시/리포트 정리하지 말고 빠르게 동작만 확인 (LLM 호출 없음)
uv run jgi --gallery tenbagger --days 1 --top 2 --max-pages 3 --dry-run
uv run jgi --days 1 --top 2 --max-pages 3 --dry-run     # krstock
# → 두 번째 실행은 "페이지 3부터 재시작" 메시지가 나와야 함

# 웹 API (소켓 없이 인프로세스로 확인)
uv run python -c "
import os,sys; sys.path.insert(0,'src')
os.environ['REPORTS_DIR']='/tmp/r'; os.environ['CACHE_DIR']='/tmp/c'
from fastapi.testclient import TestClient; from jgi.web.app import app
with TestClient(app) as c: print(c.get('/api/galleries').json())"

# 프론트 (빌드 후 jsdom 스모크)
cd web && npm install && npm run build && npm i --no-save jsdom && node uitest.cjs
```

## 환경

- Python 3.12+, `uv` 의존성 관리.
- 의존성: `httpx`, `beautifulsoup4` + `lxml`, `openai`, `python-dotenv`, `pydantic`, `tenacity`, `rich`, `fastapi`, `uvicorn`, `apscheduler`.
- `.env`에서 `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`을 읽음 (LLM 단계에만 필요). 웹은 `REPORTS_DIR`, `CACHE_DIR`, `WEB_*`, `SCHEDULE_CRON`, `REPORT_TOP`, `GALLERIES`.

## 의도적으로 안 한 것

- 댓글 수집 (사용자 결정).
- 동시 요청 (차단 위험 + 단계 단순성).
- 별도 DB (jsonl + json 파일로 충분).
- 갤러리별 별도 프로세스/DB 분리 — 한 프로세스에서 갤러리 루프로 처리 (파일 이름 접두로만 구분).
