from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Casablanca")

from public_job_adapter import normalize_anapec_job, normalize_emploi_public_job
from search import is_job_visible_now


def test_anapec_adapter_preserves_core_and_source_specific_fields():
    raw = {
        "source": "anapec",
        "source_offer_id": "1158926",
        "source_reference": "FE1308261158926",
        "global_id": "anapec:1158926",
        "title": "Téléconseiller",
        "source_title": "(8) Téléconseiller",
        "positions": 8,
        "publication_date": "2026-08-13",
        "deadline": None,
        "location": "FES",
        "contract_type": "CI",
        "contract_options": [],
        "salary": "2000 DHS",
        "company": None,
        "source_url": "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158926/resultat_recherche",
        "application": {"official": True, "reference": "FE1308261158926", "url": "https://www.anapec.org/sigec-app-rv/fr/chercheurs/postulation?ref=FE1308261158926"},
    }
    job = normalize_anapec_job(raw)
    assert job["uuid"] == "anapec:1158926"
    assert job["job_name"] == "Téléconseiller"
    assert job["positions"] == 8
    assert job["deadline"] is None
    assert job["salary"] == "2000 DHS"
    assert job["application_site"].startswith("https://www.anapec.org/")
    assert job["source_label"] == "ANAPEC"


def test_source_visibility_policy_is_independent():
    now = datetime(2026, 8, 14, 12, 0)
    anapec = {
        "source": "anapec",
        "publication_date": "2026-08-13",
        "deadline": None,
    }
    emploi = {
        "source": "emploi-public",
        "publication_date": "2026-08-13",
        "deadline": "2026-08-20T23:59:00",
    }
    expired = dict(emploi, deadline="2026-08-13T10:00:00")
    assert is_job_visible_now(anapec, now) is True
    assert is_job_visible_now(emploi, now) is True
    assert is_job_visible_now(expired, now) is False


def test_emploi_adapter_is_non_destructive():
    raw = {
        "uuid": "abc",
        "url": "https://www.emploi-public.ma/fr/concours/details/abc",
        "listing_title": "Technicien",
        "job_name": "Technicien",
        "administration": "Administration X",
        "publication_date": "2026-08-13T00:00:00",
        "deadline": "2026-08-20T23:59:00",
        "positions": 2,
    }
    job = normalize_emploi_public_job(raw)
    assert job["uuid"] == "abc"
    assert job["source"] == "emploi-public"
    assert job["global_id"] == "emploi-public:abc"
    assert job["administration"] == "Administration X"


def test_aggregate_keeps_sources_independent_and_filters_by_each_policy(tmp_path):
    from maintenance.public_refresh import _validate_aggregate

    now = datetime(2026, 8, 14, 12, 0)
    jobs = [
        normalize_emploi_public_job({
            "uuid": "ep-1",
            "url": "https://www.emploi-public.ma/fr/concours/details/ep-1",
            "listing_title": "Technicien",
            "job_name": "Technicien",
            "administration": "Administration X",
            "publication_date": "2026-08-13T00:00:00",
            "deadline": "2026-08-20T23:59:00",
            "positions": 1,
        }),
        normalize_anapec_job({
            "source": "anapec",
            "source_offer_id": "1158926",
            "source_reference": "FE1308261158926",
            "global_id": "anapec:1158926",
            "title": "Téléconseiller",
            "source_title": "(8) Téléconseiller",
            "positions": 8,
            "publication_date": "2026-08-13",
            "location": "FES",
            "contract_type": "CI",
            "source_url": "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158926/resultat_recherche",
            "application": {"official": True, "reference": "FE1308261158926", "url": "https://www.anapec.org/sigec-app-rv/fr/chercheurs/postulation?ref=FE1308261158926"},
        }),
    ]
    report = _validate_aggregate(jobs, now)
    assert report["visible_jobs"] == 2
    assert report["source_counts"] == {"anapec": 1, "emploi-public": 1}


def test_anapec_refresh_cadence_uses_lkg_manifest(tmp_path):
    import json
    from maintenance.public_refresh import _anapec_is_stale

    current = tmp_path / "current"
    current.mkdir()
    (current / "manifest.json").write_text(
        json.dumps({"published_at": "2026-08-14T08:00:00+01:00"}),
        encoding="utf-8",
    )
    assert _anapec_is_stale(current, datetime(2026, 8, 14, 12, 0, tzinfo=TZ), 6.0) is False
    assert _anapec_is_stale(current, datetime(2026, 8, 14, 15, 0, tzinfo=TZ), 6.0) is True
