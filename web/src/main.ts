import "./style.css";
import { marked } from "marked";
import DOMPurify from "dompurify";

interface GalleryInfo {
  key: string;
  name: string;
  short_name: string;
  market_label: string;
  url: string;
}

interface ReportEntry {
  slug: string;
  filename: string;
  start_date: string;
  end_date: string;
  title: string;
  mtime: number;
  size: number;
  gallery: string;
  gallery_name: string;
  gallery_short_name: string;
  market_label: string;
}

interface ReportPayload {
  content: string;
  fear_greed_score?: number;
  gallery?: string;
  gallery_name?: string;
  gallery_short_name?: string;
  market_label?: string;
}

const app = document.getElementById("app")!;

function slugFromPath(): string | null {
  const m = location.pathname.match(/^\/reports\/([^/]+)\/?$/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** 목록 화면의 선택된 탭 (?gallery=tenbagger). */
function galleryFromQuery(): string | null {
  return new URLSearchParams(location.search).get("gallery");
}

function listHref(galleryKey?: string | null): string {
  return galleryKey ? `/?gallery=${encodeURIComponent(galleryKey)}` : "/";
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

function renderFearGreedGauge(score: number, marketLabel: string): string {
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
    <div class="gauge-container">
      <div class="gauge-header">
        <span class="gauge-title">공포와 탐욕 지수</span>
        <span class="gauge-subtitle">${escapeHtml(marketLabel)}</span>
      </div>
      <div class="gauge-content">
        <div class="gauge-value">
          <span class="gauge-number">${score.toFixed(1)}</span>
          <span class="gauge-label">현재 지수</span>
        </div>
        <div class="gauge-visual">
          <svg viewBox="0 0 300 180" class="gauge-svg" role="img" aria-label="공포와 탐욕 지수: ${score.toFixed(1)}점 (${escapeHtml(marketLabel)})">
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

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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
        <span class="brand-text">DC인사이드 주식 갤 민심</span>
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

function renderTabs(
  galleries: GalleryInfo[],
  active: string,
  counts: Record<string, number>,
): string {
  const tabs = galleries
    .map((g) => {
      const isActive = g.key === active;
      const count = counts[g.key] ?? 0;
      return `
        <a class="tab${isActive ? " is-active" : ""}"
           href="${listHref(g.key)}"
           role="tab"
           aria-selected="${isActive}"
           data-gallery="${escapeHtml(g.key)}">
          <span class="tab-label">${escapeHtml(g.short_name)}</span>
          <span class="tab-count">${count}</span>
        </a>
      `;
    })
    .join("");
  return `<nav class="tabs" role="tablist" aria-label="갤러리 선택">${tabs}</nav>`;
}

function renderList(
  galleries: GalleryInfo[],
  all: ReportEntry[],
  activeKey: string,
): void {
  const activeGallery =
    galleries.find((g) => g.key === activeKey) ?? galleries[0];
  const counts: Record<string, number> = {};
  for (const e of all) {
    counts[e.gallery] = (counts[e.gallery] ?? 0) + 1;
  }
  const entries = all.filter((e) => e.gallery === activeGallery.key);

  const items = entries
    .map(
      (e) => `
      <a class="report-card card" href="/reports/${encodeURIComponent(e.slug)}">
        <time datetime="${e.start_date}">${e.start_date}</time>
        <h2>${escapeHtml(e.title)}</h2>
        <p class="meta">${fmtDate(e.mtime)} · ${Math.round(e.size / 1024)} KB</p>
      </a>
    `,
    )
    .join("");

  const body = entries.length
    ? `<section class="report-grid">${items}</section>`
    : `<section class="empty card">
         <h2>${escapeHtml(activeGallery.name)} 리포트가 없습니다</h2>
         <p>스케줄러가 전날 리포트를 생성할 때까지 기다리거나, 서버에서 수동 작업을 실행하세요.</p>
       </section>`;

  renderShell(`
    <section class="list-hero">
      <h1>일일 민심 리포트</h1>
      <p>${escapeHtml(activeGallery.name)} · ${entries.length}개 보관 중</p>
    </section>
    ${renderTabs(galleries, activeGallery.key, counts)}
    ${body}
  `);
  document.title = `${activeGallery.short_name} 민심 리포트 · JGI`;
}

function renderReport(slug: string, data: ReportPayload): void {
  const marketLabel = data.market_label ?? "시장 심리";
  let html = DOMPurify.sanitize(
    marked.parse(normalizeGeneratedAt(data.content), {
      gfm: true,
      breaks: true,
    }) as string,
  );
  const gauge =
    data.fear_greed_score !== undefined
      ? renderFearGreedGauge(data.fear_greed_score, marketLabel)
      : "";
  if (gauge) {
    html = html.replace("</h1>", `</h1>\n${gauge}`);
  }
  renderShell(`
    <nav class="breadcrumb"><a href="${listHref(data.gallery)}">← 목록</a></nav>
    <article class="report-body card prose">${html}</article>
  `);
  document.title = `${slug} · JGI`;
}

async function boot(): Promise<void> {
  // Sync scroll for background animations using requestAnimationFrame to prevent layout thrashing
  let ticking = false;
  window.addEventListener(
    "scroll",
    () => {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          document.documentElement.style.setProperty(
            "--scroll-y",
            `${window.scrollY}`,
          );
          ticking = false;
        });
        ticking = true;
      }
    },
    { passive: true },
  );

  renderShell(`<p class="loading">불러오는 중…</p>`);
  const slug = slugFromPath();

  try {
    if (slug) {
      const data = await api<ReportPayload>(
        `/api/reports/${encodeURIComponent(slug)}/json`,
      );
      renderReport(slug, data);
    } else {
      const [galleries, entries] = await Promise.all([
        api<GalleryInfo[]>("/api/galleries"),
        api<ReportEntry[]>("/api/reports"),
      ]);
      const requested = galleryFromQuery();
      const activeKey =
        galleries.find((g) => g.key === requested)?.key ??
        galleries[0]?.key ??
        "krstock";
      renderList(galleries, entries, activeKey);
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    renderShell(
      `<section class="error card"><h1>오류</h1><p>${escapeHtml(msg)}</p></section>`,
    );
  }
}

boot();
