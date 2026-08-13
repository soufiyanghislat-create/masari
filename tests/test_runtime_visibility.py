from datetime import datetime
from zoneinfo import ZoneInfo

from search import is_job_visible_now

TZ = ZoneInfo("Africa/Casablanca")


def test_runtime_visibility_accepts_open_fresh_job():
    now = datetime(2026, 8, 13, 16, 0, tzinfo=TZ)
    job = {
        "publication_date": "2026-08-10T00:00:00",
        "deadline": "2026-08-13T16:30:00",
    }
    assert is_job_visible_now(job, now)


def test_runtime_visibility_hides_expired_job_immediately():
    now = datetime(2026, 8, 13, 16, 31, tzinfo=TZ)
    job = {
        "publication_date": "2026-08-10T00:00:00",
        "deadline": "2026-08-13T16:30:00",
    }
    assert not is_job_visible_now(job, now)


def test_runtime_visibility_keeps_exact_deadline_boundary():
    now = datetime(2026, 8, 13, 16, 30, tzinfo=TZ)
    job = {
        "publication_date": "2026-08-10T00:00:00",
        "deadline": "2026-08-13T16:30:00",
    }
    assert is_job_visible_now(job, now)


def test_runtime_visibility_hides_older_than_15_days():
    now = datetime(2026, 8, 13, 12, 0, tzinfo=TZ)
    job = {
        "publication_date": "2026-07-28T00:00:00",
        "deadline": "2026-08-30T16:30:00",
    }
    assert not is_job_visible_now(job, now)


def test_runtime_visibility_hides_missing_dates():
    now = datetime(2026, 8, 13, 12, 0, tzinfo=TZ)
    assert not is_job_visible_now({"deadline": "2026-08-30T16:30:00"}, now)
    assert not is_job_visible_now({"publication_date": "2026-08-10T00:00:00"}, now)
