#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from typing import Any
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from search import is_job_visible_now, resolve_profession_query, search_by_profession
from literal_search import (
    LITERAL_PREFIX,
    LITERAL_PREFIXES,
    literal_profession_suggestions,
    merge_profession_suggestions,
    resolve_literal_profession,
    search_literal_profession,
)
from taxonomy_engine import Taxonomy
from cv_analyzer import CVAnalysisError, MAX_CV_BYTES, analyze_cv

TZ = ZoneInfo("Africa/Casablanca")
REPO = Path(__file__).resolve().parent
HTML_PATH = REPO / "web" / "index.html"
JOB_HTML_PATH = REPO / "web" / "job.html"

# Railway test mode: serve the verified frozen five-source corpus.
# Remove this flag in the final authorized production release.
EXPERIMENTAL_FROZEN_CORPUS = True

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if (not EXPERIMENTAL_FROZEN_CORPUS) and os.getenv("MASARI_DISABLE_SCHEDULER", "").strip() != "1":
        thread = threading.Thread(
            target=scheduler_loop,
            daemon=True,
            name="masari-staging-scheduler",
        )
        thread.start()
    yield


app = FastAPI(
    title="Masari Staging",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

taxonomy = Taxonomy()

_cache_lock = threading.Lock()
_cache_key: tuple[str, int] | None = None
_cache_index: dict[str, Any] | None = None

_refresh_state_lock = threading.Lock()
_refresh_running = False
_refresh_last_error = ""
_refresh_last_started = ""
_refresh_last_finished = ""


def runtime_dir() -> Path:
    explicit = os.getenv("MASARI_RUNTIME_DIR", "").strip()
    if explicit:
        return Path(explicit)

    # Kept for compatibility if a volume is ever used later, but no volume
    # is required or expected for the current hosting-only staging setup.
    railway_volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_volume:
        return Path(railway_volume) / "public" / "aggregate"

    return REPO / "runtime" / "public" / "aggregate"


def current_index_path() -> Path:
    return runtime_dir() / "current" / "search_index.json"


def current_manifest_path() -> Path:
    return runtime_dir() / "current" / "manifest.json"


def bootstrap_index_path() -> Path:
    return REPO / "bootstrap" / "search_index.json"


def bootstrap_manifest_path() -> Path:
    return REPO / "bootstrap" / "manifest.json"


def active_index_path() -> tuple[Path | None, str]:
    current = current_index_path()
    if current.exists():
        return current, "runtime"

    seed = bootstrap_index_path()
    if seed.exists():
        return seed, "bootstrap"

    return None, "none"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_index() -> tuple[dict[str, Any], str]:
    global _cache_key, _cache_index

    path, source = active_index_path()
    if path is None:
        raise FileNotFoundError("No runtime or bootstrap index is available")

    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns)

    with _cache_lock:
        if _cache_index is None or _cache_key != key:
            data = load_json(path)
            if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                raise RuntimeError("invalid search index")
            _cache_index = data
            _cache_key = key
        return _cache_index, source


def active_manifest(source: str) -> dict[str, Any]:
    path = current_manifest_path() if source == "runtime" else bootstrap_manifest_path()
    if not path.exists():
        return {}
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


JOB_DETAIL_FIELDS=("uuid","global_id","source","source_label","scope","employment_sector","ground_truth_status","ground_truth_proof","source_offer_id","source_reference","listing_title","search_title","title","job_name","administration","company","publication_date","deadline","contest_date","grade","specialties","positions","recruitment_type","contract_type","contract_options","salary","location","work_location_text","location_relation","education","experience","languages","description","profile","sector","agency","application_type","application_site","application_url","application_notice_url","opening_order_url","contest_code","url","source_url")
def public_job_detail(job: dict[str, Any]) -> dict[str, Any]:
    return {key: job.get(key) for key in JOB_DETAIL_FIELDS}
def find_visible_job(index: dict[str, Any], job_id: str) -> dict[str, Any] | None:
    needle=str(job_id or "").strip()
    for job in index.get("jobs") or []:
        ids={str(job.get("global_id") or "").strip(),str(job.get("uuid") or "").strip(),str(job.get("source_offer_id") or "").strip()}
        if needle in ids:return job if is_job_visible_now(job) else None
    return None

def refresh_status_private() -> dict[str, Any]:
    with _refresh_state_lock:
        return {
            "running": _refresh_running,
            "last_error": _refresh_last_error,
            "last_started": _refresh_last_started,
            "last_finished": _refresh_last_finished,
        }


def refresh_status_public() -> dict[str, Any]:
    status = refresh_status_private()
    return {
        "running": bool(status["running"]),
        "last_failed": bool(status["last_error"]),
        "last_started": status["last_started"],
        "last_finished": status["last_finished"],
    }


def _set_refresh_state(**changes: Any) -> None:
    global _refresh_running, _refresh_last_error
    global _refresh_last_started, _refresh_last_finished

    with _refresh_state_lock:
        if "running" in changes:
            _refresh_running = bool(changes["running"])
        if "last_error" in changes:
            _refresh_last_error = str(changes["last_error"])
        if "last_started" in changes:
            _refresh_last_started = str(changes["last_started"])
        if "last_finished" in changes:
            _refresh_last_finished = str(changes["last_finished"])


def run_refresh(mode: str) -> bool:
    if os.getenv("MASARI_DISABLE_REFRESH", "").strip() == "1":
        return False

    with _refresh_state_lock:
        global _refresh_running
        if _refresh_running:
            return False
        _refresh_running = True

    _set_refresh_state(
        last_started=datetime.now(TZ).isoformat(),
        last_error="",
    )

    cmd = [
        sys.executable,
        str(REPO / "maintenance" / "public_refresh.py"),
        "--mode",
        mode,
        "--runtime-dir",
        str(runtime_dir()),
        "--min-coverage",
        "90",
    ]

    try:
        subprocess.run(cmd, cwd=REPO, check=True)
        _set_refresh_state(
            running=False,
            last_finished=datetime.now(TZ).isoformat(),
            last_error="",
        )
        return True
    except Exception as exc:
        _set_refresh_state(
            running=False,
            last_finished=datetime.now(TZ).isoformat(),
            last_error=f"{type(exc).__name__}: {exc}",
        )
        return False


def start_refresh(mode: str) -> bool:
    with _refresh_state_lock:
        if _refresh_running:
            return False

    thread = threading.Thread(
        target=run_refresh,
        args=(mode,),
        daemon=True,
        name=f"masari-refresh-{mode}",
    )
    thread.start()
    return True


def full_run_exists_for_today(now: datetime) -> bool:
    runs_dir = runtime_dir() / "runs"
    if not runs_dir.exists():
        return False
    prefix = now.strftime("%Y%m%d-")
    return any(
        p.is_dir() and p.name.startswith(prefix) and p.name.endswith("-full")
        for p in runs_dir.iterdir()
    )


def bootstrap_mode(now: datetime) -> str | None:
    # Hosting-only Railway filesystem is ephemeral. The committed bootstrap
    # index makes the site usable immediately, while a fresh verified runtime
    # index is built in the background after every new container starts.
    if not current_index_path().exists():
        return "full"

    if (now.hour, now.minute) >= (5, 30) and not full_run_exists_for_today(now):
        return "full"

    manifest_path = current_manifest_path()
    if manifest_path.exists():
        try:
            manifest = load_json(manifest_path)
            published_at = str(manifest.get("published_at") or "")
            if published_at:
                published = datetime.fromisoformat(published_at)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=TZ)
                age_seconds = (now - published.astimezone(TZ)).total_seconds()
                if age_seconds > 5 * 3600:
                    return "quick"
        except Exception:
            return "quick"

    return None


SLOTS: dict[tuple[int, int], str] = {
    (5, 30): "full",
    (10, 30): "quick",
    (14, 30): "quick",
    (18, 30): "quick",
}


def scheduler_loop() -> None:
    mode = bootstrap_mode(datetime.now(TZ))
    if mode:
        start_refresh(mode)

    last_slot = ""
    while True:
        now = datetime.now(TZ)
        mode = SLOTS.get((now.hour, now.minute))
        slot_key = now.strftime("%Y-%m-%d-%H:%M")
        if mode and slot_key != last_slot:
            if start_refresh(mode):
                last_slot = slot_key
        time.sleep(20)


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(
        HTML_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/service-worker.js", include_in_schema=False)
def service_worker_cleanup() -> Response:
    body = (
        "self.addEventListener('install',()=>self.skipWaiting());\n"
        "self.addEventListener('activate',event=>event.waitUntil(self.registration.unregister()));\n"
    )
    return Response(
        content=body,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Service-Worker-Allowed": "/",
        },
    )


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    path, source = active_index_path()
    return {
        "ok": True,
        "ready": path is not None,
        "index_source": source,
        "service": "masari-staging",
    }


@app.get("/api/meta")
def api_meta() -> dict[str, Any]:
    try:
        index, source = load_index()
        jobs = len(index.get("jobs") or [])
        ready = True
    except Exception:
        jobs = 0
        source = "none"
        ready = False

    return {
        "ready": ready,
        "jobs": jobs,
        "index_source": source,
        "manifest": active_manifest(source),
        "refresh": refresh_status_public(),
        "timezone": "Africa/Casablanca",
    }


@app.get("/job/{job_id:path}", response_class=HTMLResponse)
def job_page(job_id: str) -> HTMLResponse:
    try:index,_=load_index();job=find_visible_job(index,unquote(job_id))
    except Exception:job=None
    if job is None:raise HTTPException(status_code=404,detail="Job not found")
    return HTMLResponse(JOB_HTML_PATH.read_text(encoding="utf-8"),headers={"Cache-Control":"no-store"})
@app.get("/api/job/{job_id:path}")
def api_job_detail(job_id: str) -> dict[str, Any]:
    try:index,index_source=load_index()
    except Exception:raise HTTPException(status_code=503,detail="Search index unavailable")
    job=find_visible_job(index,unquote(job_id))
    if job is None:raise HTTPException(status_code=404,detail="Job not found")
    return {"index_source":index_source,"job":public_job_detail(job)}


@app.post("/api/cv/analyze")
async def api_cv_analyze(
    file: UploadFile = File(...),
    limit: int = Query(default=15, ge=1, le=15),
) -> JSONResponse:
    filename = str(file.filename or "cv").strip() or "cv"
    try:
        data = await file.read(MAX_CV_BYTES + 1)
    finally:
        await file.close()

    if len(data) > MAX_CV_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "CV_TOO_LARGE", "message": "Le CV dépasse la limite de 5 Mo."},
        )

    try:
        index, index_source = load_index()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SEARCH_INDEX_UNAVAILABLE",
                "message": "L’index des offres est temporairement indisponible.",
            },
        )

    try:
        result = await run_in_threadpool(
            analyze_cv,
            filename,
            data,
            index,
            taxonomy,
            limit=limit,
        )
    except CVAnalysisError as exc:
        status = {"CV_TOO_LARGE": 413, "CV_UNSUPPORTED_FORMAT": 415}.get(exc.code, 422)
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": exc.message},
        )
    except Exception:
        raise HTTPException(
            status_code=422,
            detail={"code": "CV_ANALYSIS_FAILED", "message": "Le CV n’a pas pu être analysé."},
        )

    result["index_source"] = index_source
    return JSONResponse(result, headers={"Cache-Control": "no-store"})

@app.get("/api/suggest")
def api_suggest(
    q: str = Query(min_length=2, max_length=120),
) -> dict[str, Any]:
    query = q.strip()
    canonical = taxonomy.autocomplete(query, limit=8)
    literal = []
    try:
        index, _source = load_index()
        literal = literal_profession_suggestions(index, query, limit=8)
    except Exception:
        literal = []
    return {
        "suggestions": merge_profession_suggestions(canonical, literal, limit=8),
    }



BALANCED_SEARCH_SOURCES = (
    "emploi-public",
    "anapec",
    "smartrecruiters",
    "linkedin",
    "indeed",
)


def balanced_source_pool(rows: list[dict[str, Any]], per_source_limit: int) -> list[dict[str, Any]]:
    # Keep up to per_source_limit ranked rows from each provider.
    limit = max(int(per_source_limit), 1)
    selected: list[dict[str, Any]] = []
    known = set(BALANCED_SEARCH_SOURCES)
    for source in BALANCED_SEARCH_SOURCES:
        source_rows = [
            row for row in rows
            if str(row.get("source") or "").strip().casefold() == source
        ]
        selected.extend(source_rows[:limit])
    selected.extend(
        row for row in rows
        if str(row.get("source") or "").strip().casefold() not in known
    )
    selected.sort(key=lambda x: str(x.get("publication_date") or ""), reverse=True)
    selected.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return selected


def maybe_balanced_results(
    results: list[dict[str, Any]], *, balanced: bool, limit: int
) -> list[dict[str, Any]]:
    if not balanced:
        return results[:limit]
    return balanced_source_pool(results, limit)


@app.get("/api/search")
def api_search(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=15, ge=1, le=30),
    balanced: bool = Query(default=False),
) -> dict[str, Any]:
    try:
        index, index_source = load_index()
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="Masari is preparing the first search index.",
        )
    except Exception:
        raise HTTPException(status_code=503, detail="Search index unavailable.")

    query = q.strip()

    if query.startswith(LITERAL_PREFIXES):
        literal = resolve_literal_profession(index, query)
        if literal is not None:
            results = search_literal_profession(index, literal["profession_id"], limit=(len(index.get("jobs") or []) if balanced else limit))
            results = maybe_balanced_results(results, balanced=balanced, limit=limit)
            return {
                "selection_required": False,
                "index_source": index_source,
                "profession": {
                    "profession_id": literal["profession_id"],
                    "label": literal["label"],
                    "sector": literal.get("sector") or "ANAPEC",
                    "family": literal.get("family") or "",
                },
                "count": len(results),
                "results": results,
            }

    profession_id, suggestions = resolve_profession_query(taxonomy, query)
    if profession_id is not None:
        p = taxonomy.profession(profession_id)
        results = search_by_profession(index, profession_id, (len(index.get("jobs") or []) if balanced else limit))
        results = maybe_balanced_results(results, balanced=balanced, limit=limit)
        return {
            "selection_required": False,
            "index_source": index_source,
            "profession": {
                "profession_id": profession_id,
                "label": getattr(p, "label", profession_id),
                "sector": getattr(p, "sector", ""),
                "family": getattr(p, "family", ""),
            },
            "count": len(results),
            "results": results,
        }

    literal = resolve_literal_profession(index, query)
    if literal is not None:
        results = search_literal_profession(index, literal["profession_id"], limit=(len(index.get("jobs") or []) if balanced else limit))
        results = maybe_balanced_results(results, balanced=balanced, limit=limit)
        return {
            "selection_required": False,
            "index_source": index_source,
            "profession": {
                "profession_id": literal["profession_id"],
                "label": literal["label"],
                "sector": literal.get("sector") or "ANAPEC",
                "family": literal.get("family") or "",
            },
            "count": len(results),
            "results": results,
        }

    literal_suggestions = literal_profession_suggestions(index, query, limit=8)
    return {
        "selection_required": True,
        "suggestions": merge_profession_suggestions(suggestions, literal_suggestions, limit=8),
        "index_source": index_source,
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "staging_web:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        proxy_headers=True,
    )
