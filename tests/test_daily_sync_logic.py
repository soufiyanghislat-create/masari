from datetime import datetime
from zoneinfo import ZoneInfo

from maintenance.refresh import fresh_and_open

TZ = ZoneInfo("Africa/Casablanca")


def test_refresh_business_filter_matches_runtime_policy():
    now = datetime(2026, 8, 13, 18, 0, tzinfo=TZ)

    active = {
        "publication_date": "2026-08-01T00:00:00",
        "deadline": "2026-08-14T16:30:00",
    }
    expired = {
        "publication_date": "2026-08-12T00:00:00",
        "deadline": "2026-08-13T17:59:59",
    }
    too_old = {
        "publication_date": "2026-07-28T00:00:00",
        "deadline": "2026-08-30T16:30:00",
    }

    assert fresh_and_open(active, now) == (True, "accepted")
    assert fresh_and_open(expired, now) == (False, "deadline_expired")
    assert fresh_and_open(too_old, now) == (False, "older_than_15_days")


def test_runtime_validation_rejects_expired_job(tmp_path):
    import json
    from maintenance.refresh import validate_runtime_index

    now = datetime(2026, 8, 13, 18, 0, tzinfo=TZ)
    job = {
        "uuid": "u1",
        "url": "https://example.test/u1",
        "publication_date": "2026-08-12T00:00:00",
        "deadline": "2026-08-13T17:00:00",
        "profession_matches": [],
    }

    source = tmp_path / "jobs.json"
    index = tmp_path / "search_index.json"
    source.write_text(json.dumps([job]), encoding="utf-8")
    index.write_text(json.dumps({"jobs": [job]}), encoding="utf-8")

    try:
        validate_runtime_index(index, source, now)
    except RuntimeError as exc:
        assert "visibility gate failed" in str(exc)
    else:
        raise AssertionError("expired job must fail runtime validation")
