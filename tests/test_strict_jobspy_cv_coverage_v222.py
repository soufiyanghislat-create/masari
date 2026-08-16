from datetime import datetime
from zoneinfo import ZoneInfo

from build_public_search_index import _strict_jobspy_title_matches
from cv_analyzer import analyze_cv
from taxonomy_engine import HCP_SEARCH_MIN_SCORE, STRICT_SEARCH_MIN_SCORE, Taxonomy

TZ = ZoneInfo("Africa/Casablanca")
NOW = datetime(2026, 8, 16, 5, 30, tzinfo=TZ)

CV = """
Technicien Spécialisé en Gros Œuvres & Gestionnaire de Chantier

PROFIL PROFESSIONNEL
Technicien spécialisé en gros œuvre, avec plusieurs années d'expérience en
 dessin bâtiment, métré, suivi de chantier et gestion de projets de construction.
Actuellement Gestionnaire de Chantier.

EXPERIENCES PROFESSIONNELLES
Gestionnaire de Chantier — Entreprise BTP — Depuis 2022 (en cours)
Planification, coordination et suivi des travaux de gros œuvre.
Dessinateur Freelance — 2019 – 2022
Réalisation de plans 2D/3D sur AutoCAD et ArchiCAD.

FORMATION
Technicien Spécialisé en Gros Œuvres
Technicien Dessinateur Bâtiment

COMPETENCES TECHNIQUES
Organisation et suivi de chantier
Calcul de métrés et estimation des coûts
Réalisation de plannings de projet
AutoCAD ArchiCAD
""".strip()

TARGET_IDS = [
    "btp.conducteur_travaux",
    "btp.chef_chantier",
    "btp.dessinateur_architectural",
    "btp.technicien_genie_civil",
]


def base_job(i: int, title: str, source: str = "linkedin"):
    gid = f"{source}:strict-{i}"
    return {
        "uuid": gid,
        "global_id": gid,
        "source": source,
        "source_label": "LinkedIn" if source == "linkedin" else "Indeed",
        "scope": "private",
        "employment_sector": "private",
        "job_name": title,
        "listing_title": title,
        "company": f"Entreprise {i}",
        "location": "Casablanca, Morocco",
        "publication_date": "2026-08-15T09:00:00+01:00",
        "deadline": None,
        "ground_truth_status": "VERIFIED",
        "ground_truth_proof": "strict-direct-source",
        "location_verification": {
            "gate": "PASS",
            "evidence": "explicit_location:morocco",
        },
        "profession_ids": [],
        "profession_matches": [],
    }


def test_taxonomy_thresholds_are_not_lowered():
    assert STRICT_SEARCH_MIN_SCORE == 92.0
    assert HCP_SEARCH_MIN_SCORE == 96.0


def test_exact_btp_titles_gain_only_strict_canonical_matches():
    taxonomy = Taxonomy()
    for i, pid in enumerate(TARGET_IDS):
        profession = taxonomy.profession(pid)
        assert profession is not None
        job = base_job(i, profession.label)
        matches = _strict_jobspy_title_matches(job, taxonomy)
        assert matches, (pid, profession.label)
        assert matches[0]["profession_id"] == pid
        assert matches[0]["confidence"] in {"EXACT", "STRONG"}
        minimum = (
            STRICT_SEARCH_MIN_SCORE
            if taxonomy.profession(pid).source == "masari_market"
            else HCP_SEARCH_MIN_SCORE
        )
        assert float(matches[0]["score"]) >= minimum
        assert matches[0]["evidence"]["field"] == "job_name"


def test_description_cannot_create_jobspy_profession():
    taxonomy = Taxonomy()
    job = base_job(50, "Assistant administratif")
    job["description"] = (
        "Chef de chantier conducteur de travaux AutoCAD génie civil "
        "dessinateur architectural"
    )
    matches = _strict_jobspy_title_matches(job, taxonomy)
    assert all(not str(m["profession_id"]).startswith("btp.") for m in matches)


def test_unrelated_title_does_not_become_btp():
    taxonomy = Taxonomy()
    job = base_job(51, "Responsable marketing digital")
    matches = _strict_jobspy_title_matches(job, taxonomy)
    assert all(not str(m["profession_id"]).startswith("btp.") for m in matches)


def test_unverified_jobspy_row_cannot_gain_canonical_match():
    taxonomy = Taxonomy()
    profession = taxonomy.profession("btp.chef_chantier")
    assert profession is not None
    job = base_job(60, profession.label)
    job["ground_truth_status"] = "COLLECTED"
    assert _strict_jobspy_title_matches(job, taxonomy) == []


def test_strict_indexed_titles_raise_cv_recall_without_cv_fallback():
    taxonomy = Taxonomy()
    jobs = []
    for i in range(12):
        pid = TARGET_IDS[i % len(TARGET_IDS)]
        profession = taxonomy.profession(pid)
        assert profession is not None
        job = base_job(i, profession.label, source="linkedin" if i % 2 else "indeed")
        matches = _strict_jobspy_title_matches(job, taxonomy)
        assert matches
        job["profession_matches"] = matches
        job["profession_ids"] = [m["profession_id"] for m in matches]
        jobs.append(job)

    result = analyze_cv(
        "cv.txt",
        CV.encode("utf-8"),
        {"jobs": jobs},
        taxonomy,
        limit=15,
        now=NOW,
    )
    private = result["sector_matches"]["private"]
    assert len(private) >= 10, private
    assert result["matching_policy"]["private"]["profession_gate"] is True
    assert "literal_title_fallback" not in result["matching_policy"]["private"]
