from pathlib import Path


def test_search_result_payload_exposes_application_delivery_fields():
    text = Path("search.py").read_text(encoding="utf-8")
    for field in [
        "application_type",
        "application_site",
        "application_notice_url",
        "opening_order_url",
    ]:
        assert f'"{field}": job.get("{field}") or ""' in text
