from pathlib import Path

HTML = Path("web/index.html").read_text(encoding="utf-8")


def test_horizontal_sector_tabs_exist():
    assert "sector-tabs" in HTML
    assert "sector-tab public" in HTML
    assert "sector-tab private" in HTML
    assert "grid-template-columns:1fr 1fr" in HTML


def test_sector_labels_are_explicit_and_trilingual():
    for value in (
        "القطاع العمومي",
        "القطاع الخاص",
        "Secteur public",
        "Secteur privé",
        "Public sector",
        "Private sector",
    ):
        assert value in HTML


def test_sector_tabs_are_accessible_and_clickable():
    assert 'role="tablist"' in HTML
    assert 'role="tab"' in HTML
    assert "aria-selected" in HTML
    assert "bindSectorTabs" in HTML
    assert "activeEmploymentSector" in HTML


def test_only_selected_sector_list_is_rendered():
    assert "renderSectorTabs" in HTML
    assert "renderSectorJobs(selected,activeEmploymentSector)" in HTML
