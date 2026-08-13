from pathlib import Path


REFRESH = Path("maintenance/refresh.py").read_text(encoding="utf-8")


def test_daily_sync_runs_application_cta_gate_before_publish():
    assert "run_application_cta_gate(" in REFRESH
    main_pos = REFRESH.index("def main()")
    tail = REFRESH[main_pos:]
    gate_pos = tail.index("run_application_cta_gate(")
    build_pos = tail.index("validate_and_build(")
    publish_pos = tail.index("publish(")
    assert gate_pos < build_pos < publish_pos


def test_full_refresh_enables_network_cta_validation():
    assert 'check_network=(mode == "full")' in REFRESH


def test_manifest_exposes_cta_census_summary():
    assert '"application_cta_gate": cta_audit.get("gate")' in REFRESH
    assert '"application_cta_hard_failures": cta_audit.get("hard_failure_count")' in REFRESH
    assert '"application_cta_counts": cta_audit.get("cta_counts")' in REFRESH
    assert '"application_channel_counts": cta_audit.get("application_channel_counts")' in REFRESH
    assert '"application_cta_network_verdict_counts": cta_audit.get(' in REFRESH
