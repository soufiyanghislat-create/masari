from classifiability import evaluate_classifiable_coverage, structural_ambiguity_reasons


def job(**kwargs):
    base = {
        "uuid": "x",
        "job_name": "",
        "grade": "",
        "specialties": [],
        "profession_matches": [],
    }
    base.update(kwargs)
    return base


def match(pid):
    return {
        "profession_id": pid,
        "confidence": "EXACT",
        "source": "masari_market",
    }


def test_generic_public_technician_without_specialty_is_ambiguous():
    assert structural_ambiguity_reasons(job(
        grade="Technicien de 3ème grade - echelle 9",
    )) == ["generic_public_grade_without_specialty"]


def test_public_technician_with_specialty_is_not_ambiguous():
    assert structural_ambiguity_reasons(job(
        grade="Technicien de 3ème grade - echelle 9",
        specialties=["Développement informatique"],
    )) == []


def test_generic_aggregate_cadres_is_ambiguous():
    assert structural_ambiguity_reasons(job(
        job_name="Cadres",
    )) == ["generic_aggregate_job_name"]


def test_arabic_diacritic_before_agents_is_normalized():
    assert structural_ambiguity_reasons(job(
        job_name="َagents de maîtrise",
    )) == ["generic_aggregate_job_name"]


def test_specific_unknown_role_is_classifiable_not_ambiguous():
    assert structural_ambiguity_reasons(job(
        job_name="Chief Quantum Widget Officer",
    )) == []


def test_specific_known_recruitment_role_is_not_ambiguous():
    assert structural_ambiguity_reasons(job(
        job_name="Gestionnaire Recrutement",
        profession_matches=[match("admin.rh")],
    )) == []


def test_classifiable_coverage_excludes_only_structural_ambiguity():
    indexed = [
        job(uuid="1", job_name="Gestionnaire Recrutement",
            profession_matches=[match("admin.rh")]),
        job(uuid="2", grade="Technicien de 3ème grade - echelle 9"),
        job(uuid="3", job_name="Cadres"),
    ]
    result = evaluate_classifiable_coverage(indexed, minimum_coverage_pct=90.0)
    assert result["jobs"] == 3
    assert result["classified_jobs"] == 1
    assert result["raw_classification_coverage_pct"] == 33.33
    assert result["structurally_ambiguous_jobs"] == 2
    assert result["classifiable_jobs"] == 1
    assert result["classified_classifiable_jobs"] == 1
    assert result["classifiable_coverage_pct"] == 100.0
    assert result["unexplained_unclassified_jobs"] == 0
    assert result["gate"] is True


def test_unknown_specific_unclassified_job_lowers_hard_gate():
    indexed = [
        job(uuid="1", job_name="Known Role", profession_matches=[match("known.role")]),
        job(uuid="2", job_name="New Specific Profession"),
    ]
    result = evaluate_classifiable_coverage(indexed, minimum_coverage_pct=90.0)
    assert result["structurally_ambiguous_jobs"] == 0
    assert result["classifiable_jobs"] == 2
    assert result["classified_classifiable_jobs"] == 1
    assert result["unexplained_unclassified_jobs"] == 1
    assert result["classifiable_coverage_pct"] == 50.0
    assert result["gate"] is False


def test_ambiguous_job_receiving_profession_match_is_hard_failure():
    indexed = [
        job(
            uuid="1",
            grade="Technicien de 3ème grade - echelle 9",
            profession_matches=[match("it.technicien_informatique")],
        ),
    ]
    result = evaluate_classifiable_coverage(indexed, minimum_coverage_pct=0.0)
    assert result["ambiguous_classified_jobs"] == 1
    assert result["gate"] is False
