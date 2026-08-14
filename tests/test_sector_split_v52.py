from public_job_adapter import normalize_anapec_job, normalize_emploi_public_job
from pathlib import Path

HTML = Path("web/index.html").read_text(encoding="utf-8")
DETAIL = Path("web/job.html").read_text(encoding="utf-8")


def test_anapec_private_sector():
    j = normalize_anapec_job({
        "source_offer_id": "1",
        "source_reference": "R1",
        "global_id": "anapec:1",
        "title": "Vendeur",
        "positions": 1,
        "publication_date": "2026-08-14",
        "source_url": "https://www.anapec.org/1",
        "application": {"url": "https://www.anapec.org/apply?ref=R1"},
    })
    assert j["source"] == "anapec"
    assert j["scope"] == "private"
    assert j["employment_sector"] == "private"


def test_emploi_public_public_sector():
    j = normalize_emploi_public_job({
        "uuid": "ep1",
        "url": "https://www.emploi-public.ma/ep1",
        "publication_date": "2026-08-14",
        "deadline": "2026-08-30T23:59:00",
        "positions": 1,
    })
    assert j["source"] == "emploi-public"
    assert j["scope"] == "public"
    assert j["employment_sector"] == "public"


def test_search_ui_horizontal_sector_split():
    for x in (
        "sectorForJob",
        "renderSectorTabs",
        "renderSectorJobs",
        "bindSectorTabs",
        "sector-tabs",
        "sector-tab public",
        "sector-tab private",
        "القطاع العمومي",
        "القطاع الخاص",
        "Secteur public",
        "Secteur privé",
        "Public sector",
        "Private sector",
    ):
        assert x in HTML


def test_detail_sector():
    for x in (
        "employmentSector",
        "القطاع العمومي",
        "القطاع الخاص",
        "Secteur public",
        "Secteur privé",
    ):
        assert x in DETAIL
