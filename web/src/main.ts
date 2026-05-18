import "./style.css";
import { marked } from "marked";
import DOMPurify from "dompurify";

interface ReportEntry {
  slug: string;
  filename: string;
  start_date: string;
  end_date: string;
  title: string;
  mtime: number;
  size: number;
}

const app = document.getElementById("app")!;

function slugFromPath(): string | null {
  const m = location.pathname.match(/^\/reports\/([^/]+)\/?$/);
  return m ? decodeURIComponent(m[1]) : null;
}

const KST: Intl.DateTimeFormatOptions = { timeZone: "Asia/Seoul" };

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString("ko-KR", {
    ...KST,
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** Legacy reports used server-local (UTC) time without a zone label. */
function normalizeGeneratedAt(md: string): string {
  return md.replace(
    /^_생성:\s*(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?!\s+KST)_$/m,
    (_, date, time) => {
      const utc = new Date(`${date}T${time}Z`);
      const kst = utc
        .toLocaleString("sv-SE", { ...KST, hour12: false })
        .replace("T", " ");
      return `_생성: ${kst} KST_`;
    },
  );
}

function renderFearGreedGauge(score: number): string {
  const startAngle = -Math.PI;
  const endAngle = 0;
  const angle = startAngle + (endAngle - startAngle) * (score / 100);
  const cx = 150;
  const cy = 150;
  const radius = 120;
  const pointerX = cx + radius * Math.cos(angle);
  const pointerY = cy + radius * Math.sin(angle);

  const createSegment = (start: number, end: number, color: string) => {
    const startRad = -Math.PI + (start / 100) * Math.PI;
    const endRad = -Math.PI + (end / 100) * Math.PI;
    const x1 = cx + radius * Math.cos(startRad);
    const y1 = cy + radius * Math.sin(startRad);
    const x2 = cx + radius * Math.cos(endRad);
    const y2 = cy + radius * Math.sin(endRad);
    const largeArc = end - start > 50 ? 1 : 0;
    return `<path d="M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z" fill="${color}" opacity="0.9"/>`;
  };

  const segments = [
    createSegment(0, 20, "#c41e1e"),
    createSegment(20, 40, "#f07178"),
    createSegment(40, 60, "#e6c07b"),
    createSegment(60, 80, "#3dd68c"),
    createSegment(80, 100, "#1a7d5a"),
  ];

  return `
    <div class="gauge-container card">
      <div class="gauge-header">
        <h2>공포와 탐욕 지수</h2>
        <span class="gauge-subtitle">코스피 시장 심리</span>
      </div>
      <div class="gauge-content">
        <div class="gauge-value">
          <span class="gauge-number">${score.toFixed(1)}</span>
          <span class="gauge-label">현재 지수</span>
        </div>
        <div class="gauge-visual">
          <svg viewBox="0 0 300 180" class="gauge-svg">
            <defs>
              <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur in="SourceAlpha" stdDeviation="2"/>
                <feOffset dx="1" dy="1" result="offsetblur"/>
                <feComponentTransfer>
                  <feFuncA type="linear" slope="0.3"/>
                </feComponentTransfer>
                <feMerge>
                  <feMergeNode/>
                  <feMergeNode in="SourceGraphic"/>
                </feMerge>
              </filter>
            </defs>
            ${segments.join("")}
            <path d="M ${cx + 4 * Math.cos(angle - Math.PI / 2)} ${cy + 4 * Math.sin(angle - Math.PI / 2)}
                     L ${pointerX} ${pointerY}
                     L ${cx + 4 * Math.cos(angle + Math.PI / 2)} ${cy + 4 * Math.sin(angle + Math.PI / 2)} Z"
                  fill="#e8ecf4" filter="url(#shadow)"/>
            <circle cx="${cx}" cy="${cy}" r="6" fill="#e8ecf4"/>
            <circle cx="${cx}" cy="${cy}" r="2" fill="#141a24"/>
          </svg>
        </div>
        <div class="gauge-legend">
          <div class="legend-row">
            <div class="legend-item"><span class="legend-color" style="background: #c41e1e;"></span><span class="legend-text">극단적 공포</span></div>
            <div class="legend-item"><span class="legend-color" style="background: #f07178;"></span><span class="legend-text">공포</span></div>
            <div class="legend-item"><span class="legend-color" style="background: #e6c07b;"></span><span class="legend-text">중립</span></div>
            <div class="legend-item"><span class="legend-color" style="background: #3dd68c;"></span><span class="legend-text">탐욕</span></div>
            <div class="legend-item"><span class="legend-color" style="background: #1a7d5a;"></span><span class="legend-text">극단적 탐욕</span></div>
          </div>
        </div>
      </div>

    </div>
  `;
}

async function api<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin" });
  if (res.status === 401) {
    throw new Error("인증이 필요합니다. 브라우저 로그인 창을 확인하세요.");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

function renderShell(inner: string): void {
  app.innerHTML = `
    <header class="site-header">
      <a href="/" class="brand">
        <img src="/assets/brand-mark.png" alt="JGI" class="brand-mark" />
        <span class="brand-text">DC인사이드 한국주식 갤 민심</span>
      </a>
    </header>
    <main class="main">${inner}</main>
    <footer class="site-footer">
      <p>자동 수집·LLM 요약 · 투자 참고용</p>
      <hr class="footer-divider" />
      <p class="footer-copy">© Homin Lee <a href="mailto:i@homin.dev">i@homin.dev</a> All rights reserved.</p>
    </footer>
  `;
}

function renderList(entries: ReportEntry[]): void {
  if (!entries.length) {
    renderShell(`
      <section class="empty card">
        <h1>리포트가 없습니다</h1>
        <p>스케줄러가 전날 리포트를 생성할 때까지 기다리거나, 서버에서 수동 작업을 실행하세요.</p>
      </section>
    `);
    return;
  }

  const items = entries
    .map(
      (e) => `
      <a class="report-card card" href="/reports/${encodeURIComponent(e.slug)}">
        <time datetime="${e.start_date}">${e.start_date}</time>
        <h2>${e.title}</h2>
        <p class="meta">${fmtDate(e.mtime)} · ${Math.round(e.size / 1024)} KB</p>
      </a>
    `,
    )
    .join("");

  renderShell(`
    <section class="list-hero">
      <h1>일일 민심 리포트</h1>
      <p>${entries.length}개 보관 중</p>
    </section>
    <section class="report-grid">${items}</section>
  `);
}

function renderReport(slug: string, md: string, score?: number): void {
  const html = DOMPurify.sanitize(
    marked.parse(normalizeGeneratedAt(md), {
      gfm: true,
      breaks: true,
    }) as string,
  );
  const gauge = score !== undefined ? renderFearGreedGauge(score) : "";
  renderShell(`
    <nav class="breadcrumb"><a href="/">← 목록</a></nav>
    ${gauge}
    <article class="report-body card prose">${html}</article>
  `);
  document.title = `${slug} · JGI`;
}

async function boot(): Promise<void> {
  renderShell(`<p class="loading">불러오는 중…</p>`);
  const slug = slugFromPath();

  try {
    if (slug) {
      const data = await api<{ content: string; fear_greed_score?: number }>(
        `/api/reports/${encodeURIComponent(slug)}/json`,
      );
      renderReport(slug, data.content, data.fear_greed_score);
    } else {
      const entries = await api<ReportEntry[]>("/api/reports");
      renderList(entries);
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    renderShell(
      `<section class="error card"><h1>오류</h1><p>${msg}</p></section>`,
    );
  }
}

boot();
