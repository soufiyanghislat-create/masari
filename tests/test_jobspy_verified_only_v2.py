from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobspy_source_adapter import normalize_jobspy_source_job

ROOT = Path(__file__).resolve().parents[1]


def _read(source: str, name: str):
    return json.loads(
        (ROOT / "bootstrap" / source / name).read_text(encoding="utf-8")
    )


def test_verified_bootstrap_counts_and_manifests():
    expected = {"indeed": 179, "linkedin": 685}
    for source, count in expected.items():
        jobs = _read(source, "jobs.json")
        manifest = _read(source, "manifest.json")
        assert len(jobs) == count
        assert manifest["jobs"] == count
        assert manifest["ground_truth_gate"] == "PASS"
        assert manifest["ground_truth_policy"] == "STRICT_VERIFIED_ONLY"
        assert manifest["network_refresh_enabled"] is False
        for job in jobs:
            assert job["ground_truth_status"] == "VERIFIED"
            assert job["ground_truth_proof"]


def test_adapter_rejects_quarantined_job():
    sample = _read("indeed", "jobs.json")[0]
    broken = dict(sample)
    broken["ground_truth_status"] = "QUARANTINED"
    with pytest.raises(ValueError, match="ground_truth_status"):
        normalize_jobspy_source_job(broken)


def test_adapter_rejects_missing_proof():
    sample = _read("linkedin", "jobs.json")[0]
    broken = dict(sample)
    broken["ground_truth_proof"] = ""
    with pytest.raises(ValueError, match="ground_truth_proof"):
        normalize_jobspy_source_job(broken)
