from pathlib import Path

HTML = Path("web/index.html").read_text(encoding="utf-8")


def test_three_language_switcher_exists():
    assert 'data-lang="ar"' in HTML
    assert 'data-lang="fr"' in HTML
    assert 'data-lang="en"' in HTML
    assert "العربية" in HTML
    assert "Français" in HTML
    assert "English" in HTML


def test_core_ui_is_translated_in_all_three_languages():
    required = [
        "بحث",
        "Rechercher",
        "Search",
        "عدد المناصب",
        "Nombre de postes",
        "Number of positions",
        "تاريخ النشر",
        "Date de publication",
        "Publication date",
        "آخر أجل",
        "Date limite",
        "Application deadline",
        "فتح الإعلان الرسمي",
        "Voir l’annonce officielle",
        "View official announcement",
    ]
    for value in required:
        assert value in HTML


def test_internal_refresh_messages_are_not_public_ui():
    forbidden = [
        "النتائج متاحة الآن من النسخة الموثقة",
        "التحديث الأحدث يعمل في الخلفية",
        "البيانات محدثة",
        "آخر تحديث:",
        "index_source",
    ]
    for value in forbidden:
        assert value not in HTML


def test_source_content_is_semantically_isolated():
    assert 'class="original-body" lang="fr" dir="ltr"' in HTML
    assert 'lang="fr" dir="ltr">${esc(j.administration' in HTML


def test_direction_changes_with_language():
    assert "document.documentElement.dir=lang==='ar'?'rtl':'ltr'" in HTML


def test_profession_labels_have_ar_fr_en_variants():
    for profession_id in [
        "btp.technicien_genie_civil",
        "btp.technicien_architecture_urbanisme",
        "it.technicien_developpement_informatique",
        "finance.comptable",
        "health.infirmier",
    ]:
        assert profession_id in HTML
    assert "تقني هندسة مدنية" in HTML
    assert "Civil Engineering Technician" in HTML
    assert "Technicien génie civil" in HTML


def test_dates_use_direction_safe_numeric_format():
    assert "date-value" in HTML
    assert "${m[3]}/${m[2]}/${m[1]}" in HTML


def test_no_public_source_debug_details_block():
    assert ">بيانات المصدر<" not in HTML
    assert ">Données source<" not in HTML
    assert ">Source data<" not in HTML


def _profession_map():
    import json
    import re
    match = re.search(
        r"const PROFESSIONS=(\{.*?\});\n\nconst TAXONOMY_TEXT=",
        HTML,
        flags=re.S,
    )
    assert match, "Could not extract profession localization map"
    return json.loads(match.group(1))


def test_current_bootstrap_professions_have_localized_labels():
    import json
    bootstrap = Path("bootstrap/search_index.json")
    if not bootstrap.exists():
        return

    data = json.loads(bootstrap.read_text(encoding="utf-8"))
    active_ids = {
        profession_id
        for job in (data.get("jobs") or [])
        for profession_id in (job.get("profession_ids") or [])
    }
    localized = _profession_map()
    missing = sorted(active_ids - set(localized))
    assert not missing, f"Active profession localization missing: {missing}"

    for profession_id in active_ids:
        item = localized[profession_id]
        assert item.get("ar")
        assert item.get("fr")
        assert item.get("en")



def test_application_cta_is_trilingual_and_source_driven():
    assert "الترشح الآن" in HTML
    assert "Postuler" in HTML
    assert "Apply now" in HTML
    assert "شروط وطريقة الترشح (PDF)" in HTML
    assert "Conditions et modalités de candidature (PDF)" in HTML
    assert "Application requirements and instructions (PDF)" in HTML
    assert "function applicationCta(j){" in HTML
    assert "j.application_notice_url" in HTML
    assert "j.opening_order_url" in HTML
    assert "j.application_site" in HTML
    assert "j.application_type" in HTML
