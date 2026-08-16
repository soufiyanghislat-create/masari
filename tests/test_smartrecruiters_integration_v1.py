from datetime import datetime
from zoneinfo import ZoneInfo

from literal_search import literal_profession_for_job, resolve_literal_profession, search_literal_profession
from search import is_job_visible_now
from smartrecruiters_adapter import normalize_smartrecruiters_job

TZ = ZoneInfo("Africa/Casablanca")


def _job():
    return {
        "global_id": "smartrecruiters:Acme:abc123",
        "source": "smartrecruiters",
        "source_company_identifier": "Acme",
        "source_posting_id": "abc123",
        "job_name": "Quality Engineer",
        "company": "Acme Morocco",
        "publication_date": "2026-08-15T08:00:00Z",
        "location": {"city": "Casablanca", "country": "ma"},
        "application_site": "https://jobs.smartrecruiters.com/Acme/abc123",
    }


def test_smartrecruiters_adapter_private_no_deadline():
    row = normalize_smartrecruiters_job(_job())
    assert row["source"] == "smartrecruiters"
    assert row["scope"] == "private"
    assert row["employment_sector"] == "private"
    assert row["deadline"] is None
    assert row["positions"] is None
    assert row["url"].startswith("https://")


def test_smartrecruiters_visibility_does_not_require_deadline():
    row = normalize_smartrecruiters_job(_job())
    now = datetime(2026, 8, 15, 12, 0, tzinfo=TZ)
    assert is_job_visible_now(row, now)


def test_smartrecruiters_literal_profession():
    row = normalize_smartrecruiters_job(_job())
    literal = literal_profession_for_job(row)
    assert literal is not None
    assert literal["profession_id"].startswith("smartrecruiters.literal.")
    assert literal["job_source"] == "smartrecruiters"


def test_smartrecruiters_literal_resolution_and_search():
    row = normalize_smartrecruiters_job(_job())
    literal = literal_profession_for_job(row)
    row["literal_profession"] = literal
    index = {"jobs": [row]}
    resolved = resolve_literal_profession(index, literal["profession_id"])
    assert resolved is not None
    results = search_literal_profession(
        index,
        literal["profession_id"],
        now=datetime(2026, 8, 15, 12, 0, tzinfo=TZ),
    )
    assert len(results) == 1
    assert results[0]["source"] == "smartrecruiters"
    assert results[0]["employment_sector"] == "private"
