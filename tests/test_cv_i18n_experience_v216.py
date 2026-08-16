from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cv_analyzer import infer_explicit_experience_years, analyze_cv
from taxonomy_engine import Taxonomy

TZ = ZoneInfo("Africa/Casablanca")
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web/index.html").read_text(encoding="utf-8")


def test_age_is_not_experience():
    text = "Saif Zahdi\n28 ans\nAnalyste financier\nFormation universitaire\n"
    assert infer_explicit_experience_years(text) is None


def test_explicit_experience_phrase_is_kept():
    assert infer_explicit_experience_years("5 ans d'expérience en vente et gestion.") == 5
    assert infer_explicit_experience_years("Expérience professionnelle : 7 ans.") == 7
    assert infer_explicit_experience_years("6 years of professional experience.") == 6


def test_cv_reason_payload_contains_profession_id():
    fixture = (
        "Test Person\nCommercial\nPROFIL PROFESSIONNEL\n"
        "Commercial avec 5 ans d'expérience.\nEXPÉRIENCES PROFESSIONNELLES\n"
        "Commercial Depuis 2021\nVente conseil client commercial.\n"
        "FORMATION\nTechnicien en gestion\n"
    ).encode()
    job = {
        "global_id": "private:commercial",
        "uuid": "private:commercial",
        "source": "anapec",
        "source_label": "ANAPEC",
        "employment_sector": "private",
        "title": "Commercial",
        "job_name": "Commercial",
        "company": "Test",
        "publication_date": "2026-08-16T00:00:00+01:00",
        "deadline": None,
        "profession_ids": ["sales.commercial"],
        "profession_matches": [{
            "profession_id": "sales.commercial",
            "confidence": "EXACT",
            "searchable": True,
            "score": 100,
        }],
        "specialties": ["commercial", "vente", "client"],
    }
    result = analyze_cv(
        "cv.txt", fixture, {"jobs": [job]}, Taxonomy(),
        now=datetime(2026, 8, 16, 4, 0, tzinfo=TZ),
    )
    rows = result["sector_matches"]["private"]
    assert rows
    reason = next(
        r for r in rows[0]["reasons"]
        if r["type"] in {"profession", "related_profession"}
    )
    assert reason["profession_id"]


def test_cv_reason_uses_localized_profession_label():
    assert "function cvReasonProfessionLabel(reason)" in HTML
    assert "professionLabel(id,reason.label||'')" in HTML


def test_untranslated_hcp_labels_do_not_leak_in_arabic_or_english():
    assert "function cvProfileProfessionLabel(p)" in HTML
    assert "if(id.startsWith('hcp.') && currentLang!=='fr') return '';" in HTML


def test_source_job_titles_remain_original():
    assert "${esc(j.title||'')}" in HTML


def test_language_rerender_is_preserved():
    assert "let lastCvAnalysis=null;" in HTML
    assert "renderCvResults(lastCvAnalysis);" in HTML
