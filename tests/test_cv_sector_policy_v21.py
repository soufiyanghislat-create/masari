from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cv_analyzer import analyze_cv
from taxonomy_engine import Taxonomy

TZ = ZoneInfo("Africa/Casablanca")
ROOT = Path(__file__).resolve().parents[1]
CV_TEXT = (ROOT / "tests" / "fixtures" / "cv_construction_profile.txt").read_text(encoding="utf-8")


def job(gid, title, pid, sector, keywords):
    return {
        "global_id": gid,
        "uuid": gid,
        "source": "emploi-public" if sector == "public" else "anapec",
        "source_label": "Emploi-Public.ma" if sector == "public" else "ANAPEC",
        "employment_sector": sector,
        "title": title,
        "job_name": title,
        "company": "Test",
        "publication_date": "2026-08-16T00:00:00+01:00",
        "deadline": "2026-09-30T23:59:59+01:00" if sector == "public" else None,
        "profession_ids": [pid],
        "profession_matches": [{
            "profession_id": pid,
            "confidence": "EXACT",
            "searchable": True,
            "score": 100,
        }],
        "specialties": keywords,
        "profile": " ".join(keywords),
    }


def test_public_requires_diploma_backed_profession():
    idx = {"jobs": [
        job(
            "public:dessin",
            "Dessinateur bâtiment",
            "btp.dessinateur_architectural",
            "public",
            ["dessin", "autocad", "plans"],
        ),
        job(
            "public:rh",
            "Gestionnaire RH",
            "admin.rh",
            "public",
            ["gestion", "organisation", "francais"],
        ),
    ]}
    result = analyze_cv(
        "cv.txt", CV_TEXT.encode(), idx, Taxonomy(),
        now=datetime(2026, 8, 16, 2, 50, tzinfo=TZ),
    )
    ids = {x["global_id"] for x in result["sector_matches"]["public"]}
    assert "public:dessin" in ids
    assert "public:rh" not in ids
    assert result["matching_policy"]["public"]["diploma_gate"] is True
    assert result["matching_policy"]["public"]["experience_can_override_diploma_gate"] is False


def test_private_combines_experience_diploma_and_skills():
    idx = {"jobs": [
        job(
            "private:conducteur",
            "Conducteur de travaux",
            "btp.conducteur_travaux",
            "private",
            ["chantier", "travaux", "coordination", "gros oeuvre"],
        ),
        job(
            "private:dessin",
            "Dessinateur bâtiment",
            "btp.dessinateur_architectural",
            "private",
            ["autocad", "plans", "dessin"],
        ),
    ]}
    result = analyze_cv(
        "cv.txt", CV_TEXT.encode(), idx, Taxonomy(),
        now=datetime(2026, 8, 16, 2, 50, tzinfo=TZ),
    )
    rows = result["sector_matches"]["private"]
    ids = {x["global_id"] for x in rows}
    assert {"private:conducteur", "private:dessin"} <= ids
    assert result["matching_policy"]["private"]["diploma_gate"] is False
    assert result["matching_policy"]["private"]["profession_gate"] is True
    assert any(
        any(r["type"] == "experience_relevance" for r in row["reasons"])
        for row in rows
    )
