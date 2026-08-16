from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web/index.html").read_text(encoding="utf-8")

def _block(start_marker, end_marker):
    start = HTML.index(start_marker)
    end = HTML.index(end_marker, start)
    return HTML[start:end]

def test_staging_badge_not_rendered():
    body = HTML[HTML.index("<body>"):HTML.index("<script>")]
    assert 'id="stagingBadge"' not in body
    assert "getElementById('stagingBadge')" not in HTML

def test_trust_pills_not_rendered():
    body = HTML[HTML.index("<body>"):HTML.index("<script>")]
    assert 'class="trust-row"' not in body
    assert 'id="trustFresh"' not in body
    assert 'id="trustSources"' not in body
    assert 'id="trustApply"' not in body

def test_cv_profile_not_rendered():
    block = _block("function renderCvResults(data)", "async function analyzeAttachedCv")
    assert "const profileHtml='';" in block
    assert 'CV · Masari' not in block
    assert '<div class="cv-profile">' not in block

def test_cv_match_percentage_not_rendered():
    block = _block("function cvJobCard(j)", "function renderCvSectorTabs")
    assert "match_score" not in block
    assert "cv-match-score" not in block

def test_cv_publication_date_not_rendered():
    block = _block("function cvJobCard(j)", "function renderCvSectorTabs")
    assert "publication_date" not in block
    assert "UI[currentLang].publication" not in block

def test_normal_search_publication_date_preserved():
    block = _block("function renderSectorJobs(rows,sector)", "function renderSectorTabs")
    assert "publication_date" in block

def test_cv_matching_api_preserved():
    assert "/api/cv/analyze?limit=15" in HTML
    assert "lastCvAnalysis=d;" in HTML
    assert "sector_matches" in HTML

def test_normal_search_preserved():
    assert "/api/search?q=" in HTML
    assert "function renderSectorTabs(rows)" in HTML
