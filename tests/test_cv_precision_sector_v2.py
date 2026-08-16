from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cv_analyzer import analyze_cv
from taxonomy_engine import Taxonomy

TZ = ZoneInfo("Africa/Casablanca")
ROOT = Path(__file__).resolve().parents[1]
CV_TEXT = (ROOT / "tests" / "fixtures" / "cv_construction_profile.txt").read_text(encoding="utf-8")


def job(gid, title, pid, sector, source, keywords):
    return {
        "global_id": gid,
        "uuid": gid,
        "source": source,
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


def index():
    return {"jobs": [
        job(
            "private:conducteur",
            "Conducteur de travaux",
            "btp.conducteur_travaux",
            "private",
            "anapec",
            ["chantier", "coordination", "travaux", "gros oeuvre"],
        ),
        job(
            "public:dessinateur",
            "Dessinateur bâtiment",
            "btp.dessinateur_architectural",
            "public",
            "emploi-public",
            ["dessin", "autocad", "plans", "construction"],
        ),
        job(
            "private:metreur",
            "Métreur bâtiment",
            "btp.metreur",
            "private",
            "anapec",
            ["metre", "estimation", "couts", "batiment"],
        ),
        # These mirror the bad v1 recommendations and MUST be rejected.
        job(
            "bad:controle",
            "Assistant Contrôle Gestion",
            "finance.controleur_gestion",
            "private",
            "anapec",
            ["gestion", "assistant", "francais", "realisation"],
        ),
        job(
            "bad:formateur",
            "Formateur en Langue Française",
            "edu.formateur_professionnel",
            "public",
            "emploi-public",
            ["francais", "sidi", "formation"],
        ),
        job(
            "bad:cuisine",
            "Formateur en Arts Culinaires",
            "edu.formateur_professionnel",
            "public",
            "emploi-public",
            ["formation", "gestion"],
        ),
    ]}


def test_construction_cv_primary_role_is_site_management_not_generic_admin():
    result = analyze_cv(
        "cv.txt",
        CV_TEXT.encode("utf-8"),
        index(),
        Taxonomy(),
        now=datetime(2026, 8, 16, 2, 30, tzinfo=TZ),
    )
    ids = [row["profession_id"] for row in result["profile"]["professions"]]
    assert ids[0] in {"btp.conducteur_travaux", "btp.chef_chantier"}
    assert "admin.gestionnaire" not in ids
    assert "btp.dessinateur_architectural" in ids
    assert "btp.metreur" in ids


def test_keyword_only_unrelated_jobs_are_rejected():
    result = analyze_cv(
        "cv.txt",
        CV_TEXT.encode("utf-8"),
        index(),
        Taxonomy(),
        now=datetime(2026, 8, 16, 2, 30, tzinfo=TZ),
    )
    all_matches = [
        *result["sector_matches"]["public"],
        *result["sector_matches"]["private"],
    ]
    ids = {row["global_id"] for row in all_matches}
    assert "bad:controle" not in ids
    assert "bad:formateur" not in ids
    assert "bad:cuisine" not in ids
    assert "private:conducteur" in ids
    assert "public:dessinateur" in ids
    assert "private:metreur" in ids


def test_cv_matches_are_split_public_private_and_max_15_each():
    result = analyze_cv(
        "cv.txt",
        CV_TEXT.encode("utf-8"),
        index(),
        Taxonomy(),
        now=datetime(2026, 8, 16, 2, 30, tzinfo=TZ),
    )
    assert set(result["sector_matches"]) == {"public", "private"}
    assert len(result["sector_matches"]["public"]) <= 15
    assert len(result["sector_matches"]["private"]) <= 15
    assert result["sector_counts"]["public"] >= 1
    assert result["sector_counts"]["private"] >= 1


def test_every_recommendation_has_profession_reason():
    result = analyze_cv(
        "cv.txt",
        CV_TEXT.encode("utf-8"),
        index(),
        Taxonomy(),
        now=datetime(2026, 8, 16, 2, 30, tzinfo=TZ),
    )
    for sector in ("public", "private"):
        for row in result["sector_matches"][sector]:
            assert any(
                reason["type"] in {"profession", "related_profession"}
                for reason in row["reasons"]
            )
            assert row["match_score"] >= 50
