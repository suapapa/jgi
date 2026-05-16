# AGENTS.md

다른 AI 에이전트가 이 저장소에서 작업할 때 참고할 핵심 컨텍스트. README는 사용자용, AGENTS는 작업자용.

## 한 줄 요약

**JGI (JooGall Sentiment Index)** — DC인사이드 한국주식 갤러리(`gall.dcinside.com/mgallery/board/lists/?id=krstock`)의 일정 기간 게시글을 수집해 OpenAI 호환 LLM으로 시장 민심을 요약하는 Python CLI.

## 파이프라인 (3단계 + 리포트)

```
1) 메타 수집      → metas.jsonl  (페이지마다 append)
2) 본문 크롤링    → bodies.jsonl (글마다 append)
3) LLM 분석       → analysis.json
4) 마크다운 리포트 → reports/jgi_...md
```

각 단계는 `RunCheckpoint`에 점진적으로 저장되어 **중간 실패 시 자동 재개**됨. 같은 날짜 + 같은 `--days`이면 캐시 디렉토리가 동일하므로 그냥 재실행하면 이어한다.

## 디렉토리 / 진입점

- `src/jgi/cli.py:main` — argparse + 4단계 오케스트레이션 (체크포인트 wiring 포함)
- `src/jgi/scraper.py` — `Scraper` 클래스(httpx + tenacity 재시도), `parse_list`, `parse_view`
- `src/jgi/collector.py` — `collect_meta_since`, `fetch_bodies` (둘 다 `checkpoint=` 옵션 지원)
- `src/jgi/ranker.py` — `select_top` (조회수 + 추천수×가중치)
- `src/jgi/analyzer.py` — `Analyzer` (OpenAI 호환 클라이언트, base_url 설정 가능)
- `src/jgi/reporter.py` — 마크다운 렌더
- `src/jgi/checkpoint.py` — `RunCheckpoint` (jsonl append-only 저장)
- `src/jgi/models.py` — `PostMeta`, `Post`, `AnalysisResult` (pydantic)

CLI: `jgi` (수집·분석), `jgi-serve` (웹 UI + 스케줄러)

## 도메인 지식 (놓치기 쉬운 사실)

- **글이 매우 많다**: 한국주식 갤러리는 **하루 약 9,700건**. 7일치는 ~7만 건. 그래서:
  - 메타데이터는 전체 수집하지만 LLM에는 **샘플(추천/조회/댓글 상위 합집합 ~200건)**만 보냄 → `Analyzer._build_user_prompt` 참고.
  - 7일치 풀 수집은 ~15–25분 소요. `--days 1~2`로 먼저 검증할 것.
- **DC 페이지 구조 (재확인은 필요할 때만)**:
  - 목록: `table.gall_list tbody tr.ub-content` — 공지/AD는 `td.gall_num`이 `-`라 스킵.
  - 날짜: `td.gall_date`의 `title="2026-05-15 20:47:49"`를 그대로 KST로 파싱. 폴백으로 `HH:MM` / `YY.MM.DD`.
  - 본문: `.write_div` (또는 `.writing_view_box`).
  - URL: `/mgallery/board/view/?id=krstock&no=<N>`
- **카테고리 필터**: 기본 `{"일반", "뉴스"}`만 포함 (`DEFAULT_INCLUDE_CATEGORIES`).
- **anti-bot**: 현재 `httpx` + UA rotation + `Referer` + 딜레이로 충분히 통과. 차단되면 `cloudscraper` 도입 검토 (README 참고).

## 재개 모델 (중요)

- 캐시 키: `cache/days{N}_{YYYY-MM-DD}/` — `RunCheckpoint(cache_dir, days)`에서 `date.today()` 사용.
- `state.json`의 `last_scanned_page`부터 한 페이지 재스캔하여 안전 보강 (마지막 페이지 쓰기 도중 끊김 대비).
- `metas.jsonl` / `bodies.jsonl`은 append-only이므로 dedupe는 메모리에서 `no` 기준 set으로 수행.
- 날짜가 바뀌면 cutoff도 바뀌어 새 디렉토리가 됨 → 의도된 동작.
- `--fresh` = `checkpoint.reset()`, `--refresh-analysis` = `checkpoint.reset_analysis()`.

## LLM 출력 규약

`AnalysisResult` 스키마(영문 키, 한국어 값). 시스템 프롬프트에 명시되어 있고 `Analyzer.analyze`가 `response_format=json_object`를 우선 시도하고 실패하면 텍스트로 폴백한 뒤 `_extract_json`으로 JSON 블록을 추출함. base_url이 OpenAI가 아닌 호환 서비스인 경우 `response_format` 미지원이 흔하니 폴백 경로를 유지할 것.

## 작업 시 주의

- **새 컬렉터 옵션 추가**: `cli.py`에서 argparse → `collect_meta_since` / `fetch_bodies`로 전달. checkpoint 인자는 그대로 통과시킬 것.
- **모델 변경**: `models.py`의 pydantic 모델은 jsonl 직렬화 호환성에 영향 → 필드 추가는 기본값을 줘야 기존 캐시 로드 가능.
- **`max_pages` 기본값**: 2,000 (7일치 ~1,400페이지 + 여유). 낮추지 말 것.
- **딜레이**: 0.4–0.9초가 현재 안전선. 더 줄이면 차단 위험.
- **모바일 URL**: `m.dcinside.com/board/krstock` → 데스크탑으로 301 리다이렉트. 분기시키지 말 것.
- **댓글**: 현재 스코프 밖. 모델에 `comments` 카운트만 들어있고 본문은 댓글 미포함.
- **리포트 파일명**: 신규는 `jgi_*.md`; 웹 인덱스는 구 `krstock_*.md`도 읽음 (`reports_index.py`).

## 동작 확인 (스모크)

```bash
# 캐시/리포트 정리하지 말고 빠르게 동작만 확인
uv run jgi --days 1 --top 2 --max-pages 3 --dry-run
# → 두 번째 실행은 "페이지 3부터 재시작" 메시지가 나와야 함
uv run jgi --days 1 --top 2 --max-pages 5 --dry-run
```

## 환경

- Python 3.12+, `uv` 의존성 관리.
- 의존성: `httpx`, `beautifulsoup4` + `lxml`, `openai`, `python-dotenv`, `pydantic`, `tenacity`, `rich`.
- `.env`에서 `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`을 읽음 (LLM 단계에만 필요).

## 의도적으로 안 한 것

- 댓글 수집 (사용자 결정).
- 동시 요청 (차단 위험 + 단계 단순성).
- 별도 DB (jsonl + json 파일로 충분).
- 자동 일정 실행 — 일회성 스크립트 우선, 모듈 분리로 후속 확장 여지만 남김.
