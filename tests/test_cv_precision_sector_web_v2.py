from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_cv_results_use_public_private_tabs():
    assert "function renderCvSectorTabs(" in HTML
    assert "function bindCvSectorTabs(" in HTML
    assert "data-cv-sector=" in HTML
    assert "sector_matches" in HTML


def test_cv_profile_displays_multiple_professions():
    assert "professions.slice(0,8)" in HTML
    assert ".slice(0,6)" in HTML
    assert "cv-profile-professions" in HTML


def test_cv_unrelated_keyword_only_copy_is_not_present():
    assert "related_profession" in HTML


def test_existing_normal_sector_tabs_remain():
    assert "function renderSectorTabs(rows)" in HTML
    assert "function bindSectorTabs(rows)" in HTML
