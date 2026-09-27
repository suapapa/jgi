/**
 * 프론트엔드 스모크 테스트 (네트워크 없음).
 *
 * 빌드된 번들(src/jgi/web/static)을 jsdom에서 실행하고, API 응답을 목킹해
 * 갤러리 탭 / 목록 필터링 / 리포트 상세(게이지·breadcrumb)를 검증한다.
 *
 * 실행:
 *   cd web && npm run build
 *   npm i --no-save jsdom        # 테스트 전용 (package.json 의존성 아님)
 *   node uitest.cjs
 */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const STATIC = path.resolve(__dirname, "../src/jgi/web/static");
const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
const jsFile = fs
  .readdirSync(path.join(STATIC, "assets"))
  .find((f) => f.endsWith(".js"));
const bundle = fs.readFileSync(path.join(STATIC, "assets", jsFile), "utf8");

const galleries = [
  { key: "krstock", name: "한국주식 갤러리", short_name: "한국주식", market_label: "코스피·코스닥 시장 심리", url: "x" },
  { key: "tenbagger", name: "해외주식 갤러리", short_name: "해외주식", market_label: "해외(미국) 시장 심리", url: "y" },
];

const krEntry = {
  slug: "jgi_daily_2026-09-27",
  filename: "jgi_daily_2026-09-27.md",
  start_date: "2026-09-27",
  end_date: "2026-09-27",
  title: "한국주식 · 2026-09-27 민심 리포트",
  mtime: 1759000000,
  size: 5000,
  gallery: "krstock",
  gallery_name: "한국주식 갤러리",
  gallery_short_name: "한국주식",
  market_label: "코스피·코스닥 시장 심리",
};
const tbEntry = {
  ...krEntry,
  slug: "jgi_tenbagger_daily_2026-09-27",
  filename: "jgi_tenbagger_daily_2026-09-27.md",
  title: "해외주식 · 2026-09-27 민심 리포트",
  size: 6000,
  gallery: "tenbagger",
  gallery_name: "해외주식 갤러리",
  gallery_short_name: "해외주식",
  market_label: "해외(미국) 시장 심리",
};

// 실제 리포트와 같은 형태의 마크다운 픽스처
const md = `# 해외주식 갤러리 민심 리포트 (2026-09-27)

## 한눈에 보기
- 종합 감정: **🟡 혼조**
- 감정 분포: bullish 30% · bearish 35% · neutral 35%
- 수집 게시글: 172건 · 본문 분석: 30건 · 스캔 페이지: 9

### 요약
혼조세.

## 화제 종목

| 종목 | 언급 수 | 어조 |
|---|---:|---|
| APP | 6 | 🔴 약세 |
| AAPL | 3 | 🔴 약세 |
| TSLA | 2 | 🟢 강세 |

## 주요 화제
- 장기금리 급등

## 대표 의견
> 앱러빈 뭐하냐 — (제목: 앱러빈 급락, 조회 1234)

## 우려/리스크
- 관세

## 본문 분석 대상 (조회/추천 순)

| # | 제목 | 조회 | 추천 | 댓글 | 작성일 | 링크 |
|---:|---|---:|---:|---:|---|---|
| 1 | 앱러빈 급락 | 1234 | 10 | 2 | 2026-09-27 12:00 | [열기](https://gall.dcinside.com/x) |

---
_생성: 2026-09-28 07:40:00 KST_
`;

function makeFetch() {
  return async (u) => {
    const p = String(u);
    let body;
    if (p.startsWith("/api/galleries")) body = galleries;
    else if (p.startsWith("/api/reports/")) {
      body = {
        content: md,
        fear_greed_score: 45.0,
        gallery: "tenbagger",
        gallery_name: "해외주식 갤러리",
        gallery_short_name: "해외주식",
        market_label: "해외(미국) 시장 심리",
      };
    } else if (p.startsWith("/api/reports")) body = [krEntry, tbEntry];
    else throw new Error("unexpected fetch " + p);
    return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
  };
}

async function render(pageUrl) {
  const vc = new VirtualConsole();
  const dom = new JSDOM(html, {
    url: pageUrl,
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole: vc,
  });
  const { window } = dom;
  window.fetch = makeFetch();
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  window.requestAnimationFrame = (cb) => setTimeout(cb, 0);
  window.eval(bundle);
  await new Promise((r) => setTimeout(r, 60)); // boot() 의 async 완료 대기
  return window.document;
}

const q = (doc, sel) => Array.from(doc.querySelectorAll(sel));

(async () => {
  const fails = [];
  const check = (name, cond, detail) => {
    console.log(`${cond ? "PASS" : "FAIL"}: ${name}${detail ? " — " + detail : ""}`);
    if (!cond) fails.push(name);
  };

  // 1) 기본 목록 → 첫 갤러리(한국주식) 탭
  {
    const doc = await render("http://localhost/");
    const tabs = q(doc, ".tabs .tab");
    check("탭 2개 렌더", tabs.length === 2, tabs.map((t) => t.textContent.replace(/\s+/g, " ").trim()).join(" / "));
    check("첫 탭 active = 한국주식", tabs[0].classList.contains("is-active") && tabs[0].getAttribute("aria-selected") === "true");
    check("탭 링크에 gallery 쿼리", tabs[1].getAttribute("href") === "/?gallery=tenbagger", tabs[1].getAttribute("href"));
    check("탭 카운트 배지 1/1", q(doc, ".tab-count").map((e) => e.textContent).join(",") === "1,1");
    const cards = q(doc, ".report-card");
    check("한국주식 탭에 카드 1개", cards.length === 1 && cards[0].textContent.includes("한국주식 · 2026-09-27"), cards.length + "개");
    check("hero 라벨", doc.querySelector(".list-hero p").textContent.includes("한국주식 갤러리"), doc.querySelector(".list-hero p").textContent);
    check("다른 탭 리포트 안 섞임", !doc.body.textContent.includes("해외주식 · 2026-09-27"));
  }

  // 2) 해외주식 탭 (?gallery=tenbagger)
  {
    const doc = await render("http://localhost/?gallery=tenbagger");
    const tabs = q(doc, ".tabs .tab");
    check("해외주식 탭 active", tabs[1].classList.contains("is-active"), tabs.map((t) => t.className).join(" | "));
    const cards = q(doc, ".report-card");
    check("해외주식 카드만", cards.length === 1 && cards[0].textContent.includes("해외주식 · 2026-09-27"), cards.length + "개");
    check("카드 링크 slug", cards[0].getAttribute("href") === "/reports/jgi_tenbagger_daily_2026-09-27", cards[0].getAttribute("href"));
    check("document.title 갱신", doc.title === "해외주식 민심 리포트 · JGI", doc.title);
  }

  // 3) 알 수 없는 gallery 파라미터 → 첫 갤러리로 폴백
  {
    const doc = await render("http://localhost/?gallery=doesnotexist");
    check("알 수 없는 탭 → 첫 갤러리 폴백", q(doc, ".tabs .tab")[0].classList.contains("is-active"));
  }

  // 4) 리포트 상세 — 제목/게이지/breadcrumb
  {
    const doc = await render("http://localhost/reports/jgi_tenbagger_daily_2026-09-27");
    check("본문 h1 렌더", doc.querySelector(".prose h1").textContent.includes("해외주식 갤러리 민심 리포트"), doc.querySelector(".prose h1").textContent);
    const gauge = doc.querySelector(".gauge-container");
    check("게이지 삽입", !!gauge);
    check("게이지 부제 = 해외(미국) 시장 심리", gauge.textContent.includes("해외(미국) 시장 심리"));
    check("게이지 숫자 45.0", gauge.querySelector(".gauge-number").textContent === "45.0");
    check("breadcrumb → 해외주식 목록", doc.querySelector(".breadcrumb a").getAttribute("href") === "/?gallery=tenbagger", doc.querySelector(".breadcrumb a").getAttribute("href"));
    check("마크다운 표 렌더", doc.querySelectorAll(".prose table").length >= 1);
    check("화제 종목 표 내용", doc.body.textContent.includes("APP"));
  }

  console.log(fails.length ? `\n${fails.length} FAILED: ${fails.join(", ")}` : "\nALL PASS");
  process.exit(fails.length ? 1 : 0);
})();
