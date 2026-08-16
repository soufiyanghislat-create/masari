from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web/index.html").read_text(encoding="utf-8")


def test_cv_analysis_is_kept_for_language_rerender():
    assert "let lastCvAnalysis=null;" in HTML
    assert "lastCvAnalysis=d;" in HTML
    assert "renderCvResults(lastCvAnalysis);" in HTML


def test_language_switch_rerenders_cv_instead_of_clearing_it():
    anchor = "if(lastCvAnalysis){"
    assert anchor in HTML
    block = HTML[HTML.index(anchor):HTML.index(anchor) + 220]
    assert "renderCvResults(lastCvAnalysis)" in block
    assert "state.textContent=''" in block


def test_cv_profile_language_names_are_localized():
    assert "const localizedLangs=langs.map(" in HTML
    assert "UI[currentLang].languageNames?.[code]||code" in HTML
    assert "localizedLangs.length?localizedLangs.join(', ')" in HTML


def test_cv_confidence_is_localized_in_all_languages():
    assert "confidenceHigh:'ثقة عالية'" in HTML
    assert "confidenceMedium:'ثقة متوسطة'" in HTML
    assert "confidenceLow:'ثقة منخفضة'" in HTML
    assert "confidenceHigh:'Confiance élevée'" in HTML
    assert "confidenceMedium:'Confiance moyenne'" in HTML
    assert "confidenceLow:'Confiance faible'" in HTML
    assert "confidenceHigh:'High confidence'" in HTML
    assert "confidenceMedium:'Medium confidence'" in HTML
    assert "confidenceLow:'Low confidence'" in HTML


def test_sector_tabs_still_localize():
    assert "function cvSectorLabels()" in HTML
    assert "القطاع العمومي" in HTML
    assert "Secteur public" in HTML
    assert "Public sector" in HTML
    assert "القطاع الخاص" in HTML
    assert "Secteur privé" in HTML
    assert "Private sector" in HTML


def test_profession_labels_still_use_current_language():
    assert "professionLabel(p.profession_id,p.label)" in HTML
    assert "professions.slice(0,6)" in HTML


def test_new_or_removed_cv_invalidates_cached_analysis():
    assert "selectedCvFile=file;lastCvAnalysis=null;" in HTML
    assert "selectedCvFile=null;lastCvAnalysis=null;cvFile.value=''" in HTML


def test_language_change_does_not_call_cv_api_again():
    start = HTML.index("function setLanguage(lang)")
    end = HTML.index("function formatDate", start)
    block = HTML[start:end]
    assert "/api/cv/analyze" not in block
    assert "fetch(" not in block


def test_normal_search_language_behavior_remains_without_cv():
    assert "state.textContent=UI[lang].start;" in HTML
    assert "content.innerHTML='';" in HTML
