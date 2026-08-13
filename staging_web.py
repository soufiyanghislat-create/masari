#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from search import resolve_profession_query, search_by_profession
from taxonomy_engine import Taxonomy

TZ = ZoneInfo("Africa/Casablanca")
REPO = Path(__file__).resolve().parent
HTML_PATH = REPO / "web" / "index.html"

app = FastAPI(
    title="Masari Staging",
    docs_url=None,
    redoc_url=None,
)

taxonomy = Taxonomy()

_cache_lock = threading.Lock()
_cache_mtime_ns: int | None = None
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

    railway_volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_volume:
        return Path(railway_volume) / "emploi_public"

    return REPO / "runtime" / "emploi_public"


def current_index_path() -> Path:
    return runtime_dir() / "current" / "search_index.json"


def current_manifest_path() -> Path:
    return runtime_dir() / "current" / "manifest.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_index() -> dict[str, Any]:
    global _cache_mtime_ns, _cache_index
    path = current_index_path()
    if not path.exists():
        raise FileNotFoundError(path)

    stat = path.stat()
    with _cache_lock:
        if _cache_index is None or _cache_mtime_ns != stat.st_mtime_ns:
            data = load_json(path)
            if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                raise RuntimeError("invalid search index")
            _cache_index = data
            _cache_mtime_ns = stat.st_mtime_ns
        return _cache_index


def manifest() -> dict[str, Any]:
    path = current_manifest_path()
    if not path.exists():
        return {}
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def refresh_status() -> dict[str, Any]:
    with _refresh_state_lock:
        return {
            "running": _refresh_running,
            "last_error": _refresh_last_error,
            "last_started": _refresh_last_started,
            "last_finished": _refresh_last_finished,
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

    started = datetime.now(TZ).isoformat()
    _set_refresh_state(last_started=started, last_error="")

    cmd = [
        sys.executable,
        str(REPO / "maintenance" / "refresh.py"),
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
    if not current_index_path().exists():
        return "full"

    if now.hour >= 6 and not full_run_exists_for_today(now):
        return "full"

    m = manifest()
    published_at = str(m.get("published_at") or "")
    if published_at:
        try:
            published = datetime.fromisoformat(published_at)
            if published.tzinfo is None:
                published = published.replace(tzinfo=TZ)
            age_seconds = (now - published.astimezone(TZ)).total_seconds()
            if age_seconds > 5 * 3600:
                return "quick"
        except ValueError:
            return "quick"
    return None


SLOTS: dict[tuple[int, int], str] = {
    (5, 30): "full",
    (10, 30): "quick",
    (14, 30): "quick",
    (18, 30): "quick",
}


def scheduler_loop() -> None:
    now = datetime.now(TZ)
    mode = bootstrap_mode(now)
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


@app.on_event("startup")
def startup() -> None:
    if os.getenv("MASARI_DISABLE_SCHEDULER", "").strip() == "1":
        return
    thread = threading.Thread(
        target=scheduler_loop,
        daemon=True,
        name="masari-staging-scheduler",
    )
    thread.start()


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(
        HTML_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    ready = current_index_path().exists()
    return {
        "ok": True,
        "ready": ready,
        "service": "masari-staging",
    }


@app.get("/api/meta")
def api_meta() -> dict[str, Any]:
    try:
        index = load_index()
        jobs = len(index.get("jobs") or [])
        ready = True
    except Exception:
        jobs = 0
        ready = False

    return {
        "ready": ready,
        "jobs": jobs,
        "manifest": manifest(),
        "refresh": refresh_status(),
        "timezone": "Africa/Casablanca",
    }


@app.get("/api/suggest")
def api_suggest(
    q: str = Query(min_length=2, max_length=120),
) -> dict[str, Any]:
    return {
        "suggestions": taxonomy.autocomplete(q.strip(), limit=8),
    }


@app.get("/api/search")
def api_search(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=15, ge=1, le=30),
) -> dict[str, Any]:
    try:
        index = load_index()
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="Masari is preparing the first verified index.",
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Index unavailable: {exc}")

    query = q.strip()
    profession_id, suggestions = resolve_profession_query(taxonomy, query)

    if profession_id is None:
        return {
            "selection_required": True,
            "suggestions": suggestions,
        }

    p = taxonomy.profession(profession_id)
    results = search_by_profession(index, profession_id, limit)

    return {
        "selection_required": False,
        "profession": {
            "profession_id": profession_id,
            "label": getattr(p, "label", profession_id),
            "sector": getattr(p, "sector", ""),
            "family": getattr(p, "family", ""),
        },
        "count": len(results),
        "results": results,
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
