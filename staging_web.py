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

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("MASARI_DISABLE_SCHEDULER", "").strip() != "1":
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
        return Path(railway_volume) / "emploi_public"

    return REPO / "runtime" / "emploi_public"


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
        index, index_source = load_index()
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="Masari is preparing the first search index.",
        )
    except Exception:
        raise HTTPException(status_code=503, detail="Search index unavailable.")

    query = q.strip()
    profession_id, suggestions = resolve_profession_query(taxonomy, query)

    if profession_id is None:
        return {
            "selection_required": True,
            "suggestions": suggestions,
            "index_source": index_source,
        }

    p = taxonomy.profession(profession_id)
    results = search_by_profession(index, profession_id, limit)

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


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "staging_web:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        proxy_headers=True,
    )
