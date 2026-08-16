from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cv_analyzer import CVAnalysisError, analyze_cv, extract_cv_text, infer_explicit_experience_years
from taxonomy_engine import Taxonomy

TZ = ZoneInfo("Africa/Casablanca")


def _sample_cv() -> bytes:
    return (
        "Soufiyan Example\n"
        "Technicien génie civil\n"
        "5 ans d'expérience en gestion de chantier, métrés et suivi des travaux.\n"
        "AutoCAD Excel dessin architectural béton chantier génie civil.\n"
        "Langues: français anglais arabe.\n"
        "Contact: test.person@example.com +212 600 000 000\n"
    ).encode("utf-8")


def _index():
    today = "2026-08-16T00:00:00+01:00"
    return {"jobs": [
        {
            "global_id": "anapec:1", "uuid": "anapec:1", "source": "anapec",
            "source_label": "ANAPEC", "employment_sector": "private",
            "title": "Technicien génie civil", "job_name": "Technicien génie civil",
            "company": "Entreprise BTP", "publication_date": today, "deadline": None,
            "profession_ids": ["btp.technicien_genie_civil"],
            "profession_matches": [{"profession_id": "btp.technicien_genie_civil", "score": 100, "confidence": "EXACT", "searchable": True}],
            "specialties": ["AutoCAD", "gestion de chantier", "métré"],
            "profile": "Suivi de chantier et métrés",
        },
        {
            "global_id": "anapec:2", "uuid": "anapec:2", "source": "anapec",
            "source_label": "ANAPEC", "employment_sector": "private",
            "title": "Comptable", "job_name": "Comptable", "company": "Cabinet",
            "publication_date": today, "deadline": None,
            "profession_ids": ["finance.comptable"],
            "profession_matches": [{"profession_id": "finance.comptable", "score": 100, "confidence": "EXACT", "searchable": True}],
            "specialties": ["comptabilité", "fiscalité"],
        },
    ]}


def test_txt_extraction_and_size_metadata():
    text, meta = extract_cv_text("cv.txt", _sample_cv())
    assert "Technicien génie civil" in text
    assert meta["extension"] == ".txt"
    assert meta["bytes"] == len(_sample_cv())


def test_explicit_years():
    assert infer_explicit_experience_years("5 ans d'expérience") == 5
    assert infer_explicit_experience_years("2 years puis 7 ans") == 7


def test_cv_profession_and_job_match_without_pii_return():
    result = analyze_cv(
        "cv.txt", _sample_cv(), _index(), Taxonomy(),
        now=datetime(2026, 8, 16, 2, 0, tzinfo=TZ),
    )
    assert result["profile"]["professions"]
    assert result["profile"]["professions"][0]["profession_id"] == "btp.technicien_genie_civil"
    assert result["matches"]
    assert result["matches"][0]["global_id"] == "anapec:1"
    assert result["matches"][0]["match_score"] > 40
    serialized = str(result)
    assert "test.person@example.com" not in serialized
    assert "+212 600 000 000" not in serialized
    assert result["privacy"]["stored"] is False
    assert result["privacy"]["raw_text_returned"] is False


def test_unsupported_extension_rejected():
    with pytest.raises(CVAnalysisError) as exc:
        extract_cv_text("cv.jpg", b"x" * 200)
    assert exc.value.code == "CV_UNSUPPORTED_FORMAT"


def test_short_text_rejected():
    with pytest.raises(CVAnalysisError) as exc:
        extract_cv_text("cv.txt", b"short")
    assert exc.value.code == "CV_TEXT_TOO_SHORT"
