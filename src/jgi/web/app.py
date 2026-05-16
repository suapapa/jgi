from __future__ import annotations

import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .reports_index import list_reports, read_report
from .scheduler import JobState, create_scheduler, run_scheduled_job

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _scheduler = create_scheduler(REPORTS_DIR, CACHE_DIR, job_state)
    _scheduler.start()
    logger.info("스케줄러 시작 (reports=%s)", REPORTS_DIR)
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
    return snap


@app.get("/api/reports")
def api_reports(_: None = Depends(verify_credentials)):
    entries = list_reports(REPORTS_DIR)
    return [e.to_dict() for e in entries]


@app.get("/api/reports/{slug}")
def api_report(slug: str, _: None = Depends(verify_credentials)):
    content = read_report(REPORTS_DIR, slug)
    if content is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")


def _run_job_bg(target_date: date | None, force: bool) -> None:
    try:
        run_scheduled_job(
            reports_dir=REPORTS_DIR,
            cache_dir=CACHE_DIR,
            target_date=target_date,
            top=TOP_DEFAULT,
            force=force,
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
    background_tasks.add_task(_run_job_bg, target, body.force)
    return {"queued": True, "date": body.date}


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

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8080"))
    uvicorn.run("jgi.web.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
