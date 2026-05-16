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

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  });
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
        <span class="brand-mark">KR</span>
        <span class="brand-text">한국주식 갤 민심</span>
      </a>
      <p class="tagline">DC인사이드 커뮤니티 일일 요약</p>
    </header>
    <main class="main">${inner}</main>
    <footer class="site-footer">자동 수집·LLM 요약 · 투자 참고용</footer>
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
    `
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

function renderReport(slug: string, md: string): void {
  const html = DOMPurify.sanitize(
    marked.parse(md, { gfm: true, breaks: true }) as string
  );
  renderShell(`
    <nav class="breadcrumb"><a href="/">← 목록</a></nav>
    <article class="report-body card prose">${html}</article>
  `);
  document.title = `${slug} · 한국주식 갤 민심`;
}

async function boot(): Promise<void> {
  renderShell(`<p class="loading">불러오는 중…</p>`);
  const slug = slugFromPath();

  try {
    if (slug) {
      const res = await fetch(`/api/reports/${encodeURIComponent(slug)}`, {
        credentials: "same-origin",
      });
      if (!res.ok) throw new Error("리포트를 찾을 수 없습니다");
      const md = await res.text();
      renderReport(slug, md);
    } else {
      const entries = await api<ReportEntry[]>("/api/reports");
      renderList(entries);
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    renderShell(`<section class="error card"><h1>오류</h1><p>${msg}</p></section>`);
  }
}

boot();
