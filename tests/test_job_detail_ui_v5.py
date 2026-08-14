from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import staging_web

HTML = Path("web/index.html").read_text(encoding="utf-8")
DETAIL = Path("web/job.html").read_text(encoding="utf-8")
TZ = ZoneInfo("Africa/Casablanca")


def _block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def test_results_delegate_to_horizontal_sector_tabs():
    fn = _block(HTML, "function results(d){", "function directLocalId")
    assert "renderSectorTabs(rows)" in fn
    assert "bindSectorTabs(rows)" in fn
    assert "activeEmploymentSector" in HTML


def test_horizontal_sector_renderer_contains_clickable_job_links():
    fn = _block(HTML, "function renderSectorJobs(", "function renderSectorTabs(")
    assert 'class="job-link"' in fn
    assert 'href="/job/' in fn
    assert "encodeURIComponent(id)" in fn


def test_search_results_do_not_inline_full_job_details():
    area = _block(HTML, "function renderSectorJobs(", "function directLocalId")
    for forbidden in (
        "applicationCta(j)",
        "originalBlock(j",
        "j.salary",
        "j.deadline",
        "j.contract_type",
        "j.contract_options",
        "j.description",
        "j.profile",
    ):
        assert forbidden not in area


def test_detail_page_fields_and_application_link():
    assert "fetch('/api/job/'" in DETAIL
    assert "job.salary" in DETAIL
    assert "job.contract_options" in DETAIL
    assert "job.work_location_text" in DETAIL
    assert "application_url" in DETAIL
    assert "application_site" in DETAIL
    assert "application_notice_url" in DETAIL
    assert "opening_order_url" in DETAIL


def test_detail_helpers():
    today = datetime.now(TZ).date().isoformat()
    j = {
        "uuid": "anapec:1",
        "global_id": "anapec:1",
        "source_offer_id": "1",
        "source": "anapec",
        "scope": "private",
        "employment_sector": "private",
        "publication_date": today,
        "salary": "5000",
        "profession_matches": [{"x": 1}],
    }
    assert staging_web.find_visible_job({"jobs": [j]}, "1") is j
    assert staging_web.find_visible_job({"jobs": [j]}, "anapec:1") is j
    d = staging_web.public_job_detail(j)
    assert d["salary"] == "5000"
    assert d["employment_sector"] == "private"
    assert "profession_matches" not in d


def test_detail_routes():
    src = Path("staging_web.py").read_text(encoding="utf-8")
    assert '@app.get("/job/{job_id:path}"' in src
    assert '@app.get("/api/job/{job_id:path}"' in src
