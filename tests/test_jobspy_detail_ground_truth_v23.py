from __future__ import annotations

import json
from pathlib import Path

from staging_web import public_job_detail

ROOT = Path(__file__).resolve().parents[1]
INDEX = (
    ROOT / "runtime" / "public" / "aggregate-jobspy-verified-v2"
    / "current" / "search_index.json"
)


def _sample(source: str):
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    return next(
        j for j in index["jobs"]
        if str(j.get("source") or "").casefold() == source
    )


def test_public_job_detail_preserves_indeed_ground_truth():
    job = _sample("indeed")
    detail = public_job_detail(job)
    assert detail["ground_truth_status"] == "VERIFIED"
    assert detail["ground_truth_proof"]


def test_public_job_detail_preserves_linkedin_ground_truth():
    job = _sample("linkedin")
    detail = public_job_detail(job)
    assert detail["ground_truth_status"] == "VERIFIED"
    assert detail["ground_truth_proof"]
