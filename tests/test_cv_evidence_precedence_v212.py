from datetime import datetime
from zoneinfo import ZoneInfo

from cv_analyzer import analyze_cv
from taxonomy_engine import Taxonomy

TZ = ZoneInfo("Africa/Casablanca")


def _job(gid, title, pid, sector="private"):
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
        "specialties": [title, "chantier", "autocad", "construction"],
    }


def test_explicit_title_beats_generic_summary_context():
    cv = (
        "Test Person\n"
        "Technicien génie civil\n"
        "5 ans d'expérience en gestion de chantier, métrés et suivi des travaux.\n"
        "AutoCAD Excel construction.\n"
    ).encode("utf-8")

    result = analyze_cv(
        "cv.txt",
        cv,
        {"jobs": [_job(
            "private:gc",
            "Technicien génie civil",
            "btp.technicien_genie_civil",
        )]},
        Taxonomy(),
        now=datetime(2026, 8, 16, 3, 0, tzinfo=TZ),
    )

    assert result["profile"]["professions"][0]["profession_id"] == (
        "btp.technicien_genie_civil"
    )


def test_public_diploma_evidence_survives_profile_candidate_limit():
    cv = (
        "Test Person\n"
        "Gestionnaire de Chantier\n"
        "PROFIL PROFESSIONNEL\n"
        "Actuellement Gestionnaire de Chantier. Suivi et coordination des travaux.\n"
        "EXPÉRIENCES PROFESSIONNELLES\n"
        "Gestionnaire de Chantier — Entreprise Depuis 2022 (en cours)\n"
        "Planification coordination suivi chantier gros oeuvre.\n"
        "Dessinateur Freelance 2019 - 2022\n"
        "AutoCAD ArchiCAD plans construction.\n"
        "FORMATION\n"
        "Technicien Spécialisé en Gros Œuvres\n"
        "Technicien Dessinateur Bâtiment\n"
        "COMPÉTENCES TECHNIQUES\n"
        "Métrés estimation coûts AutoCAD ArchiCAD.\n"
    ).encode("utf-8")

    result = analyze_cv(
        "cv.txt",
        cv,
        {"jobs": [_job(
            "public:dessin",
            "Dessinateur bâtiment",
            "btp.dessinateur_architectural",
            sector="public",
        )]},
        Taxonomy(),
        now=datetime(2026, 8, 16, 3, 0, tzinfo=TZ),
    )

    public_ids = {
        row["global_id"]
        for row in result["sector_matches"]["public"]
    }
    assert "public:dessin" in public_ids


def test_diploma_words_outside_formation_do_not_create_public_eligibility():
    cv = (
        "Test Person\n"
        "Commercial\n"
        "Profil avec intérêt pour le dessin bâtiment et AutoCAD.\n"
        "Expérience commerciale et relation client.\n"
    ).encode("utf-8")

    result = analyze_cv(
        "cv.txt",
        cv,
        {"jobs": [_job(
            "public:dessin",
            "Dessinateur bâtiment",
            "btp.dessinateur_architectural",
            sector="public",
        )]},
        Taxonomy(),
        now=datetime(2026, 8, 16, 3, 0, tzinfo=TZ),
    )

    assert result["sector_matches"]["public"] == []
