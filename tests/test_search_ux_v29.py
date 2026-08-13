from __future__ import annotations

from search import (
    UNIQUE_FUZZY_AUTOSELECT_MIN_SCORE,
    resolve_profession_query,
    search_by_profession,
)


class FakeTaxonomy:
    def __init__(self, *, by_id=None, exact=None, suggestions=None):
        self.by_id = by_id or {}
        self._exact = exact or []
        self._suggestions = suggestions or []

    def exact_profession_ids(self, query):
        return list(self._exact)

    def autocomplete(self, query, limit=8):
        return list(self._suggestions)[:limit]


def _match(profession_id, label, *, field="context_rule", score=99.0):
    return {
        "profession_id": profession_id,
        "label": label,
        "score": score,
        "confidence": "EXACT",
        "searchable": True,
        "evidence": {
            "field": field,
            "matched_term": "fixture",
        },
    }


def test_unique_high_confidence_typo_auto_selects():
    taxonomy = FakeTaxonomy(
        suggestions=[
            {
                "profession_id": "btp.technicien_genie_civil",
                "label": "Technicien génie civil",
                "score": UNIQUE_FUZZY_AUTOSELECT_MIN_SCORE + 1,
            }
        ]
    )
    profession_id, suggestions = resolve_profession_query(
        taxonomy,
        "technicien genie ccivil",
    )
    assert profession_id == "btp.technicien_genie_civil"
    assert suggestions == []


def test_unique_low_confidence_suggestion_still_requires_selection():
    taxonomy = FakeTaxonomy(
        suggestions=[
            {
                "profession_id": "btp.technicien_genie_civil",
                "label": "Technicien génie civil",
                "score": UNIQUE_FUZZY_AUTOSELECT_MIN_SCORE - 1,
            }
        ]
    )
    profession_id, suggestions = resolve_profession_query(taxonomy, "weak typo")
    assert profession_id is None
    assert len(suggestions) == 1


def test_multiple_professions_never_auto_select():
    taxonomy = FakeTaxonomy(
        suggestions=[
            {"profession_id": "btp.dessinateur_architectural", "score": 920},
            {"profession_id": "industry.dessinateur_industriel", "score": 920},
            {"profession_id": "btp.dessinateur_projeteur", "score": 920},
        ]
    )
    profession_id, suggestions = resolve_profession_query(taxonomy, "dessinateur")
    assert profession_id is None
    assert len(suggestions) == 3


def test_context_rule_result_uses_profession_display_title_and_preserves_source():
    pid = "it.technicien_informatique"
    search_title = (
        "Électricité-Maintenance industrielle / "
        "Électricité (éclairage public) / Génie Civil"
    )
    literal_title = (
        "Avis de concours de recrutement - Technicien de 3ème grade - 4 postes"
    )
    job = {
        "uuid": "fixture-1",
        "search_title": search_title,
        "listing_title": literal_title,
        "job_name": "",
        "specialties": [
            "Électricité-Maintenance industrielle",
            "Électricité (éclairage public)",
            "Génie Civil",
            "Maintenance Informatique et réseaux",
        ],
        "publication_date": "2026-08-10T00:00:00",
        "deadline": "2026-08-28T16:30:00",
        "profession_matches": [
            _match(pid, "Technicien informatique", field="context_rule")
        ],
        "administration": "Province fixture",
        "positions": 4,
        "url": "https://example.test/job",
    }

    rows = search_by_profession({"jobs": [job]}, pid, limit=15)
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Technicien informatique"
    assert row["source_title"] == literal_title
    assert row["search_title"] == search_title
    assert row["matched_profession_label"] == "Technicien informatique"
    assert "Maintenance Informatique et réseaux" in row["specialties"]


def test_direct_job_name_remains_authoritative_display_title():
    pid = "finance.comptable"
    job = {
        "uuid": "fixture-2",
        "search_title": "Régisseur Comptable",
        "listing_title": "Avis de recrutement - Régisseur Comptable - 1 poste",
        "job_name": "Régisseur Comptable",
        "specialties": [],
        "publication_date": "2026-08-05T00:00:00",
        "deadline": "2026-08-20T23:59:00",
        "profession_matches": [
            _match(pid, "Comptable", field="job_name", score=100.0)
        ],
        "administration": "SDL fixture",
        "positions": 1,
        "url": "https://example.test/job2",
    }

    rows = search_by_profession({"jobs": [job]}, pid, limit=15)
    assert rows[0]["title"] == "Régisseur Comptable"
    assert rows[0]["source_title"] == "Avis de recrutement - Régisseur Comptable - 1 poste"
    assert rows[0]["search_title"] == "Régisseur Comptable"
