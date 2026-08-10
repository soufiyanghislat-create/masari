from datetime import datetime
from zoneinfo import ZoneInfo

from search import rank_job
from taxonomy_engine import Taxonomy


def test_autocomplete_dessin_returns_architectural_choice():
    taxonomy = Taxonomy()
    rows = taxonomy.autocomplete("dessin", limit=10)
    ids = [row["profession_id"] for row in rows]
    assert "btp.dessinateur_architectural" in ids


def test_diploma_mapping_is_fixed_not_ai():
    taxonomy = Taxonomy()
    ids = [p.id for p in taxonomy.diploma_professions("Technicien en dessin de bâtiment")]
    assert "btp.dessinateur_architectural" in ids
    assert "btp.dessinateur_projeteur" in ids
    assert "btp.technicien_bureau_etudes" in ids


def test_classify_emploi_public_specialty_dessin_batiment():
    taxonomy = Taxonomy()
    job = {
        "listing_title": "Avis de concours de recrutement de Technicien de 3ème grade",
        "job_name": "",
        "grade": "Technicien de 3ème grade - Echelle 9",
        "specialties": ["Dessin de bâtiment"],
    }
    matches = taxonomy.classify_job(job)
    ids = [m["profession_id"] for m in matches]
    assert "btp.dessinateur_architectural" in ids


def test_one_announcement_can_map_to_multiple_professions_without_duplication():
    taxonomy = Taxonomy()
    job = {
        "uuid": "one-announcement",
        "listing_title": "Avis de concours de recrutement de Technicien de 3ème grade",
        "job_name": "",
        "grade": "Technicien de 3ème grade",
        "specialties": ["Développement informatique", "Production horticole"],
    }
    matches = taxonomy.classify_job(job)
    ids = {m["profession_id"] for m in matches}
    assert "it.developpeur_logiciel" in ids
    assert "agri.horticulture" in ids
    assert job["uuid"] == "one-announcement"


def test_rank_prefers_stronger_profession_match():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("Africa/Casablanca"))
    exact = {
        "publication_date": "2026-08-10T00:00:00",
        "deadline": "2026-08-20T16:30:00",
        "profession_matches": [{"profession_id": "btp.dessinateur_architectural", "score": 100}],
    }
    weaker = {
        "publication_date": "2026-08-10T00:00:00",
        "deadline": "2026-08-20T16:30:00",
        "profession_matches": [{"profession_id": "btp.dessinateur_architectural", "score": 80}],
    }
    score_exact, _ = rank_job(exact, "btp.dessinateur_architectural", now)
    score_weaker, _ = rank_job(weaker, "btp.dessinateur_architectural", now)
    assert score_exact > score_weaker


def test_autocomplete_uses_hcp_only_as_fallback():
    taxonomy = Taxonomy()
    rows = taxonomy.autocomplete("dessin", limit=10)
    assert rows
    assert all(row["source"] == "masari_market" for row in rows)
    assert not any("caricatur" in row["label"].casefold() for row in rows)
    assert not any("instituteur" in row["label"].casefold() for row in rows)


def test_autocomplete_can_still_fallback_to_hcp_long_tail():
    taxonomy = Taxonomy()
    rows = taxonomy.autocomplete("caricaturistes", limit=10)
    assert rows
    assert any(row["source"] == "hcp_nap2014" for row in rows)
