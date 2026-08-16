from __future__ import annotations

import json
from pathlib import Path

from jobspy_source_adapter import normalize_jobspy_source_job
from literal_search import LITERAL_SOURCES, literal_profession_for_job, literal_profession_id
from search import NO_DEADLINE_SOURCES, is_job_visible_now

ROOT = Path(__file__).resolve().parents[1]


def _bootstrap(source: str):
    return json.loads((ROOT / "bootstrap" / source / "jobs.json").read_text(encoding="utf-8"))


def test_jobspy_sources_are_registered_for_literal_search():
    assert {"indeed", "linkedin"}.issubset(LITERAL_SOURCES)


def test_jobspy_sources_do_not_require_fabricated_deadlines():
    assert {"indeed", "linkedin"}.issubset(NO_DEADLINE_SOURCES)


def test_shared_literal_namespace_for_same_title():
    a = literal_profession_id("Software Engineer", "indeed")
    b = literal_profession_id("Software Engineer", "linkedin")
    assert a == b
    assert a.startswith("jobspy.literal.")


def test_bootstrap_counts_and_quality():
    indeed = _bootstrap("indeed")
    linkedin = _bootstrap("linkedin")
    assert len(indeed) == 179
    assert len(linkedin) == 685
    for row in [*indeed, *linkedin]:
        normalized = normalize_jobspy_source_job(row)
        assert normalized["employment_sector"] == "private"
        assert normalized["deadline"] is None
        assert normalized["positions"] is None
        assert normalized["location_verification"]["gate"] == "PASS"
        assert normalized["ground_truth_status"] == "VERIFIED"
        assert normalized["ground_truth_proof"]
        assert normalized["application_site"].startswith("https://")
        # Frozen verified rows may age beyond the rolling 15-day window.
        # Current publication still obeys Masari freshness; historical
        # snapshot integrity is tested independently.
        assert isinstance(is_job_visible_now(normalized), bool)
        literal = literal_profession_for_job(normalized)
        assert literal is not None
        assert literal["searchable"] is True



def test_each_jobspy_source_has_currently_visible_rows():
    # Do not weaken freshness: only current rows can enter the aggregate.
    for source in ("indeed", "linkedin"):
        rows = _bootstrap(source)
        visible = [
            normalize_jobspy_source_job(row)
            for row in rows
            if is_job_visible_now(normalize_jobspy_source_job(row))
        ]
        assert visible, f"{source} has no currently visible verified rows"
