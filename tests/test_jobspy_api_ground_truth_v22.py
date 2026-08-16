from __future__ import annotations

import json
from pathlib import Path

from literal_search import search_literal_profession
from search import is_job_ground_truth_verified, is_job_visible_now, search_by_profession

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime" / "public" / "aggregate-jobspy-verified-v2"
INDEX = RUNTIME / "current" / "search_index.json"


def _index():
    return json.loads(INDEX.read_text(encoding="utf-8"))


def test_runtime_ground_truth_gate_rejects_quarantined_jobspy():
    index = _index()
    sample = next(j for j in index["jobs"] if j.get("source") in {"indeed", "linkedin"})
    assert is_job_ground_truth_verified(sample) is True
    assert is_job_visible_now(sample) is True

    broken = dict(sample)
    broken["ground_truth_status"] = "QUARANTINED"
    assert is_job_ground_truth_verified(broken) is False
    assert is_job_visible_now(broken) is False

    broken2 = dict(sample)
    broken2["ground_truth_proof"] = ""
    assert is_job_ground_truth_verified(broken2) is False
    assert is_job_visible_now(broken2) is False


def test_literal_serializer_preserves_ground_truth_fields():
    index = _index()
    sample = next(
        j for j in index["jobs"]
        if j.get("source") in {"indeed", "linkedin"}
        and isinstance(j.get("literal_profession"), dict)
    )
    pid = sample["literal_profession"]["profession_id"]
    rows = search_literal_profession(index, pid, limit=15)
    assert rows
    for row in rows:
        if row.get("source") in {"indeed", "linkedin"}:
            assert row["ground_truth_status"] == "VERIFIED"
            assert row["ground_truth_proof"]


def test_canonical_serializer_preserves_ground_truth_fields():
    index = _index()
    sample = next(
        j for j in index["jobs"]
        if j.get("source") in {"indeed", "linkedin"}
        and j.get("profession_matches")
    )
    pid = sample["profession_matches"][0]["profession_id"]
    rows = search_by_profession(index, pid, limit=15)
    assert rows
    jobspy_rows = [r for r in rows if r.get("source") in {"indeed", "linkedin"}]
    assert jobspy_rows
    for row in jobspy_rows:
        assert row["ground_truth_status"] == "VERIFIED"
        assert row["ground_truth_proof"]
