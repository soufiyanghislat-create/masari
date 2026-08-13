from application_cta_audit import (
    CTA_DETAIL,
    CTA_EMPLOI_PUBLIC,
    CTA_EXTERNAL,
    CTA_NOTICE,
    CTA_ORDER,
    CHANNEL_EMAIL,
    CHANNEL_EMPLOI_PUBLIC,
    CHANNEL_EXTERNAL,
    CHANNEL_PHYSICAL,
    CHANNEL_POSTAL,
    build_report,
    structural_record,
)


UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DETAIL = f"https://www.emploi-public.ma/fr/concours/details/{UUID}"
NOTICE = (
    "https://www.emploi-public.ma/fr/concours/download/fichiers_att/"
    f"{UUID}/0"
)
ORDER = f"https://www.emploi-public.ma/fr/concours/download/arrete/{UUID}"


def job(**updates):
    row = {
        "uuid": UUID,
        "url": DETAIL,
        "administration": "Test",
        "application_type": "",
        "application_site": "",
        "application_notice_url": "",
        "opening_order_url": "",
    }
    row.update(updates)
    return row


def test_external_online_application_has_direct_postuler_cta():
    row = structural_record(
        job(
            application_type="dépôt en ligne sur le site de l'administration",
            application_site="https://jobs.example.ma/apply/1",
        )
    )
    assert row["channel"] == CHANNEL_EXTERNAL
    assert row["cta_mode"] == CTA_EXTERNAL
    assert row["target"] == "https://jobs.example.ma/apply/1"
    assert row["failures"] == []


def test_emploi_public_online_application_uses_detail_page():
    row = structural_record(job(application_type="sur emploi-public"))
    assert row["channel"] == CHANNEL_EMPLOI_PUBLIC
    assert row["cta_mode"] == CTA_EMPLOI_PUBLIC
    assert row["target"] == DETAIL


def test_email_channel_is_reported_but_notice_drives_cta():
    row = structural_record(
        job(
            application_type="dépôt en ligne sur le site de l'administration",
            application_site="rh@example.ma",
            application_notice_url=NOTICE,
        )
    )
    assert row["channel"] == CHANNEL_EMAIL
    assert row["cta_mode"] == CTA_NOTICE
    assert row["target"] == NOTICE


def test_postal_channel_uses_notice_document():
    row = structural_record(
        job(
            application_type="envoi par courrier postal",
            application_notice_url=NOTICE,
        )
    )
    assert row["channel"] == CHANNEL_POSTAL
    assert row["cta_mode"] == CTA_NOTICE


def test_physical_channel_can_use_opening_order_fallback():
    row = structural_record(
        job(
            application_type="dépôt physique au siège",
            opening_order_url=ORDER,
        )
    )
    assert row["channel"] == CHANNEL_PHYSICAL
    assert row["cta_mode"] == CTA_ORDER


def test_missing_application_metadata_falls_back_to_official_detail():
    row = structural_record(job())
    assert row["cta_mode"] == CTA_DETAIL
    assert row["target"] == DETAIL
    assert row["failures"] == []
    assert "OFFICIAL_DETAIL_ONLY" in row["warnings"]


def test_cross_announcement_notice_is_hard_failure():
    wrong = (
        "https://www.emploi-public.ma/fr/concours/download/fichiers_att/"
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/0"
    )
    row = structural_record(job(application_notice_url=wrong))
    assert "INVALID_OR_CROSS_ANNOUNCEMENT_NOTICE_URL" in row["failures"]


def test_census_gate_passes_for_valid_structural_cases_without_network():
    report = build_report(
        [
            job(application_type="sur emploi-public"),
            job(application_notice_url=NOTICE),
            job(application_site="https://jobs.example.ma/apply"),
            job(),
        ],
        check_network=False,
    )
    assert report["jobs"] == 4
    assert report["actionable_coverage_pct"] == 100.0
    assert report["hard_failure_count"] == 0
    assert report["gate"] == "PASS"
    assert report["cta_counts"][CTA_EMPLOI_PUBLIC] == 1
    assert report["cta_counts"][CTA_NOTICE] == 1
    assert report["cta_counts"][CTA_EXTERNAL] == 1
    assert report["cta_counts"][CTA_DETAIL] == 1
