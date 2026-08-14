from pathlib import Path

from taxonomy_engine import Taxonomy
from search import resolve_profession_query


def test_i18n_search_file_exists():
    assert Path("taxonomy/search_i18n.json").exists()


def test_french_english_arabic_resolve_same_profession():
    taxonomy = Taxonomy()
    pid_fr, _ = resolve_profession_query(taxonomy, "infirmier")
    pid_en, _ = resolve_profession_query(taxonomy, "nurse")
    pid_ar, _ = resolve_profession_query(taxonomy, "ممرض")
    assert pid_fr == "health.infirmier"
    assert pid_fr == pid_en == pid_ar


def test_multilingual_autocomplete_prefers_closest_completion():
    taxonomy = Taxonomy()
    en = taxonomy.autocomplete("nurs", limit=8)
    ar = taxonomy.autocomplete("ممر", limit=8)
    assert en and ar
    assert en[0]["profession_id"] == "health.infirmier"
    assert any(x["profession_id"] == "health.infirmier" for x in ar)


def test_query_i18n_does_not_replace_source_classification_terms():
    taxonomy = Taxonomy()
    profession = taxonomy.profession("health.infirmier")
    assert profession is not None
    source_terms = set(profession.terms)
    query_terms = set(taxonomy.query_terms(profession))
    assert source_terms.issubset(query_terms)
    assert "Nurse" in query_terms
    assert "ممرض" in query_terms


def test_i18n_exact_lookup_prefers_market_profession():
    taxonomy = Taxonomy()
    assert taxonomy.exact_profession_ids("nurse") == ["health.infirmier"]
    assert taxonomy.exact_profession_ids("ممرض") == ["health.infirmier"]
