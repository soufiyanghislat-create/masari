from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
STAGING = (ROOT / "staging_web.py").read_text(encoding="utf-8")
REQ = (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_inline_plus_not_separate_cv_page():
    assert 'id="cvPlus"' in HTML
    assert 'id="cvFile"' in HTML
    assert 'id="cvAttachment"' in HTML
    assert 'href="/cv"' not in HTML
    assert '@app.get("/cv"' not in STAGING


def test_existing_search_box_remains_primary_ui():
    assert 'id="professionSearch"' in HTML
    assert 'id="q"' in HTML
    assert 'id="go"' in HTML
    assert "async function search()" in HTML


def test_cv_upload_is_triggered_from_same_search_button():
    assert "async function submitSearch()" in HTML
    assert "if(selectedCvFile)" in HTML
    assert "await analyzeAttachedCv()" in HTML
    assert "go.addEventListener('click',submitSearch)" in HTML


def test_plus_opens_hidden_file_input():
    assert "cvPlus.addEventListener('click',()=>cvFile.click())" in HTML
    assert '.pdf,.docx,.txt' in HTML


def test_inline_cv_api_exists():
    assert '@app.post("/api/cv/analyze")' in STAGING
    assert "UploadFile" in STAGING
    assert "run_in_threadpool" in STAGING
    assert '"Cache-Control": "no-store"' in STAGING


def test_no_cv_storage_language():
    assert "CV_STORAGE=FALSE" not in HTML
    assert "لا نحفظ السيرة الذاتية" in HTML
    assert "Le CV n’est pas conservé" in HTML
    assert "Your CV is not stored" in HTML


def test_parser_dependencies_pinned():
    assert "pypdf==6.14.2" in REQ
    assert "python-docx==1.2.0" in REQ
    assert "python-multipart==0.0.32" in REQ
