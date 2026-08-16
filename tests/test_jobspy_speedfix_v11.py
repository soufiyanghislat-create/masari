from __future__ import annotations

from build_public_search_index import JOBSPY_PREVERIFIED_SOURCES, _preverified_jobspy_matches
from taxonomy_engine import Taxonomy


def _job(matches):
    return {
        "source": "linkedin",
        "global_id": "linkedin:test",
        "location_verification": {"gate": "PASS"},
        "profession_matches": matches,
    }


def test_jobspy_sources_use_preverified_path():
    assert JOBSPY_PREVERIFIED_SOURCES == {"indeed", "linkedin"}


def test_preverified_match_keeps_only_safe_canonical_rows():
    taxonomy = Taxonomy()
    known = taxonomy.market[0]
    rows = _preverified_jobspy_matches(
        _job([
            {
                "profession_id": known.id,
                "label": known.label,
                "source": known.source,
                "confidence": "EXACT",
                "score": 100.0,
                "searchable": True,
            },
            {
                "profession_id": known.id,
                "label": known.label,
                "source": known.source,
                "confidence": "RELATED",
                "score": 80.0,
                "searchable": False,
            },
            {
                "profession_id": "does.not.exist",
                "confidence": "EXACT",
                "score": 100.0,
                "searchable": True,
            },
        ]),
        taxonomy,
    )
    assert len(rows) == 1
    assert rows[0]["profession_id"] == known.id


def test_unmatched_jobspy_job_remains_literal_candidate():
    taxonomy = Taxonomy()
    assert _preverified_jobspy_matches(_job([]), taxonomy) == []
