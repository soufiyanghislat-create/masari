from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CV = (ROOT / "cv_analyzer.py").read_text(encoding="utf-8")


def _card_block() -> str:
    start = HTML.index("function cvJobCard(j)")
    end = HTML.index("function renderCvSectorTabs", start)
    return HTML[start:end]


def test_cv_card_does_not_read_or_render_match_reasons():
    card = _card_block()
    assert "j.reasons" not in card
    assert "cv-reasons" not in card
    assert "cv-reason" not in card


def test_cv_card_keeps_job_identity_fields():
    card = _card_block()
    assert "j.title" in card
    assert "j.company" in card
    assert "j.source_label" in card
    assert "j.location" in card


def test_match_reasons_remain_backend_internal_data():
    assert '"reasons": reasons' in CV
    assert 'diploma_eligibility' in CV
    assert 'experience_relevance' in CV
    assert 'diploma_support' in CV


def test_normal_search_ui_is_not_changed_by_this_fix():
    assert "function renderSectorJobs(rows,sector)" in HTML
    assert "function renderSectorTabs(rows)" in HTML
