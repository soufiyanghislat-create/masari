from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = (ROOT / "maintenance/jobspy_refresh.py").read_text(encoding="utf-8")
REFRESH = (ROOT / "maintenance/public_refresh.py").read_text(encoding="utf-8")
STAGING = (ROOT / "staging_web.py").read_text(encoding="utf-8")
REQ = (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_same_jobspy_engine_for_both_sources():
    assert 'SUPPORTED = {"indeed", "linkedin"}' in COLLECTOR
    assert 'site_name=[source]' in COLLECTOR
    assert 'search_term=""' in COLLECTOR
    assert 'location="Morocco"' in COLLECTOR
    assert 'distance=50' in COLLECTOR
    assert 'hours_old=WINDOW_HOURS' in COLLECTOR
    assert 'results_wanted=RESULTS_WANTED' in COLLECTOR


def test_15_day_and_strict_date_gate():
    assert 'WINDOW_HOURS = 360' in COLLECTOR
    assert 'age < 0 or age > 15' in COLLECTOR
    assert 'return None, "missing_date"' in COLLECTOR


def test_morocco_location_and_dedup_gates():
    assert 'morocco_location_unverified' in COLLECTOR
    assert 'location_verification' in COLLECTOR
    assert 'seen_ids' in COLLECTOR
    assert 'seen_urls' in COLLECTOR


def test_no_bypass_or_proxy_configuration():
    assert 'proxies=None' in COLLECTOR
    assert 'CAPTCHA_BYPASS=FALSE' in COLLECTOR
    assert 'RATE_LIMIT_BYPASS=FALSE' in COLLECTOR


def test_public_refresh_calls_same_collector_twice():
    assert 'maintenance" / "jobspy_refresh.py"' in REFRESH
    assert 'for source_name in ("indeed", "linkedin")' in REFRESH
    assert '"--source", source_name' in REFRESH


def test_scheduler_enabled_and_all_sources_visible():
    assert 'EXPERIMENTAL_FROZEN_CORPUS = False' in STAGING
    assert 'SOURCE_SCHEDULE_POLICY' in STAGING
    for source in ("emploi-public", "anapec", "smartrecruiters", "indeed", "linkedin"):
        assert f'"{source}"' in STAGING


def test_jobspy_is_pinned():
    assert 'python-jobspy @ git+https://github.com/speedyapply/JobSpy.git@fda080a373e8226f3fd60635323f5da9af9892b1' in REQ
