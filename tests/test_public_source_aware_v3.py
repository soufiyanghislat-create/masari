from __future__ import annotations

from datetime import datetime

from literal_search import (
    LITERAL_PREFIX,
    literal_profession_for_job,
    literal_profession_suggestions,
    merge_profession_suggestions,
    resolve_literal_profession,
    search_literal_profession,
)


def _job(title="Ergothérapeute", **kwargs):
    base = {
        "uuid": "anapec:1",
        "global_id": "anapec:1",
        "source": "anapec",
        "source_label": "ANAPEC",
        "source_offer_id": "1",
        "job_name": title,
        "title": title,
        "listing_title": title,
        "publication_date": "2026-08-13",
        "deadline": None,
        "positions": 1,
        "url": "https://www.anapec.org/example/1",
        "application_site": "https://www.anapec.org/postulation?ref=X",
        "profession_matches": [],
        "specialties": [],
    }
    base.update(kwargs)
    literal = literal_profession_for_job(base)
    if literal:
        base["literal_profession"] = literal
    return base


def test_anapec_explicit_title_gets_stable_literal_profession():
    a = literal_profession_for_job(_job("Assistante Dentaire"))
    b = literal_profession_for_job(_job("assistante dentaire"))
    assert a["profession_id"] == b["profession_id"]
    assert a["profession_id"].startswith(LITERAL_PREFIX)
    assert a["confidence"] == "EXACT"


def test_literal_suggestion_finds_word_inside_verified_title():
    index = {"jobs": [_job("Employé Polyvalent De Restauration (Cuisinier, Serveur, Barman)")]}
    rows = literal_profession_suggestions(index, "cuisinier")
    assert len(rows) == 1
    assert rows[0]["source"] == "anapec_literal"


def test_exact_literal_title_resolves():
    index = {"jobs": [_job("Ergothérapeute")]}
    row = resolve_literal_profession(index, "ergotherapeute")
    assert row is not None
    assert row["label"] == "Ergothérapeute"


def test_canonical_label_wins_over_identical_literal_label():
    canonical = [{"profession_id": "health.ergo", "label": "Ergothérapeute", "source": "hcp_nap2014", "score": 1000}]
    literal = [{"profession_id": f"{LITERAL_PREFIX}x", "label": "Ergothérapeute", "source": "anapec_literal", "score": 1000}]
    rows = merge_profession_suggestions(canonical, literal)
    assert len(rows) == 1
    assert rows[0]["profession_id"] == "health.ergo"


def test_literal_search_obeys_anapec_visibility_without_deadline():
    index = {"jobs": [_job("Ergothérapeute")]}
    pid = index["jobs"][0]["literal_profession"]["profession_id"]
    rows = search_literal_profession(index, pid, limit=15, now=datetime.fromisoformat("2026-08-14T12:00:00+01:00"))
    assert len(rows) == 1
    assert rows[0]["source"] == "anapec"
    assert rows[0]["deadline"] is None
