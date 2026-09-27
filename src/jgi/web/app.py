from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..galleries import DEFAULT_GALLERY, GALLERIES, get_gallery
from .reports_index import extract_fear_greed_score, list_reports, read_report
from .scheduler import JobState, configured_galleries, create_scheduler, run_scheduled_job

load_dotenv()
logger = logging.getLogger(__name__)

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "cache"))
WEB_USERNAME = os.getenv("WEB_USERNAME", "")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")
TOP_DEFAULT = int(os.getenv("REPORT_TOP", "30"))

STATIC_DIR = Path(__file__).resolve().parent / "static"

job_state = JobState()
_scheduler = None
security = HTTPBasic(auto_error=False)


def _auth_enabled() -> bool:
    return bool(WEB_USERNAME and WEB_PASSWORD)


def verify_credentials(
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> None:
    if not _auth_enabled():
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    ok_user = secrets.compare_digest(credentials.username, WEB_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, WEB_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


class JobRequest(BaseModel):
    date: str | None = None
    force: bool = False
    gallery: str | None = None


class ReportResponse(BaseModel):
    content: str
    fear_greed_score: float | None = None
    gallery: str | None = None
    gallery_name: str | None = None
    gallery_short_name: str | None = None
    market_label: str | None = None


class GalleryResponse(BaseModel):
    key: str
    name: str
    short_name: str
    market_label: str
    url: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _scheduler = create_scheduler(REPORTS_DIR, CACHE_DIR, job_state)
    _scheduler.start()
    logger.info(
        "스케줄러 시작 (reports=%s, galleries=%s)",
        REPORTS_DIR,
        ",".join(g.key for g in configured_galleries()),
    )
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="JooGall Sentiment Index", lifespan=lifespan)


@app.get("/api/health")
def health(_: None = Depends(verify_credentials)):
    return {"ok": True}


@app.get("/api/status")
def api_status(_: None = Depends(verify_credentials)):
    snap = job_state.snapshot()
    snap["reports_dir"] = str(REPORTS_DIR.resolve())
    snap["auth"] = _auth_enabled()
    snap["galleries"] = [g.key for g in configured_galleries()]
    return snap


@app.get("/api/galleries", response_model=list[GalleryResponse])
def api_galleries(_: None = Depends(verify_credentials)):
    return [
        GalleryResponse(
            key=g.key,
            name=g.name,
            short_name=g.short_name,
            market_label=g.market_label,
            url=g.url,
        )
        for g in configured_galleries()
    ]


@app.get("/api/reports")
def api_reports(
    gallery: str | None = Query(None, description="갤러리 key (미지정 시 전체)"),
    _: None = Depends(verify_credentials),
):
    if gallery:
        try:
            get_gallery(gallery)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
    entries = list_reports(REPORTS_DIR, gallery=gallery)
    return [e.to_dict() for e in entries]


@app.get("/api/reports/{slug}")
def api_report(slug: str, _: None = Depends(verify_credentials)):
    content = read_report(REPORTS_DIR, slug)
    if content is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")


@app.get("/api/reports/{slug}/json", response_model=ReportResponse)
def api_report_json(slug: str, _: None = Depends(verify_credentials)):
    content = read_report(REPORTS_DIR, slug)
    if content is None:
        raise HTTPException(status_code=404, detail="Report not found")
    score = extract_fear_greed_score(content)
    entry = next((e for e in list_reports(REPORTS_DIR) if e.slug == slug), None)
    gallery = GALLERIES.get(entry.gallery, DEFAULT_GALLERY) if entry else DEFAULT_GALLERY
    return ReportResponse(
        content=content,
        fear_greed_score=score,
        gallery=gallery.key,
        gallery_name=gallery.name,
        gallery_short_name=gallery.short_name,
        market_label=gallery.market_label,
    )


def _run_job_bg(target_date: date | None, force: bool, galleries) -> None:
    try:
        run_scheduled_job(
            reports_dir=REPORTS_DIR,
            cache_dir=CACHE_DIR,
            target_date=target_date,
            top=TOP_DEFAULT,
            force=force,
            galleries=galleries,
            state=job_state,
        )
    except Exception:
        pass


@app.post("/api/jobs")
def api_trigger_job(
    body: JobRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_credentials),
):
    snap = job_state.snapshot()
    if snap["running"]:
        raise HTTPException(status_code=409, detail="Job already running")
    target = date.fromisoformat(body.date) if body.date else None
    try:
        galleries = (
            [get_gallery(body.gallery)] if body.gallery else configured_galleries()
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    background_tasks.add_task(_run_job_bg, target, body.force, galleries)
    return {
        "queued": True,
        "date": body.date,
        "galleries": [g.key for g in galleries],
    }


# SPA: API routes registered above; static files last
if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/")
    def index(_: None = Depends(verify_credentials)):
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/reports/{slug}")
    def report_page(
        slug: str,
        raw: bool = Query(False, description="true면 마크다운 원문(plain text)"),
        _: None = Depends(verify_credentials),
    ):
        if raw:
            content = read_report(REPORTS_DIR, slug)
            if content is None:
                raise HTTPException(status_code=404, detail="Report not found")
            return PlainTextResponse(
                content,
                media_type="text/plain; charset=utf-8",
            )
        return FileResponse(STATIC_DIR / "index.html")
else:

    @app.get("/")
    def no_frontend(_: None = Depends(verify_credentials)):
        return {
            "message": "Frontend not built. Run: cd web && npm install && npm run build",
            "api": "/api/reports",
        }


def main() -> None:
    import uvicorn
    import copy
    from datetime import datetime, timezone, timedelta

    KST = timezone(timedelta(hours=9))
    logging.Formatter.converter = lambda *args: datetime.now(KST).timetuple()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S KST")

    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["formatters"]["default"]["fmt"] = "%(asctime)s [%(levelprefix)s] %(message)s"
    log_config["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S KST"
    log_config["formatters"]["access"]["fmt"] = '%(asctime)s [%(levelprefix)s] %(client_addr)s - "%(request_line)s" %(status_code)s'
    log_config["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S KST"

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8080"))
    uvicorn.run("jgi.web.app:app", host=host, port=port, reload=False, log_config=log_config)


if __name__ == "__main__":
    main()
