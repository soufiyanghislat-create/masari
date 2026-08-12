from taxonomy_engine import Taxonomy, normalize


def rows(query: str, limit: int = 50) -> list[dict]:
    return Taxonomy().autocomplete(query, limit=limit)


def ids(query: str, limit: int = 50) -> list[str]:
    return [row["profession_id"] for row in rows(query, limit)]


def test_assistant_direction_exact_alias_has_single_precise_owner():
    result = rows("assistante de direction")
    assert result[0]["profession_id"] == "admin.assistant_direction"
    assert "admin.secretaire" not in {r["profession_id"] for r in result}


def test_responsable_hse_exact_alias_has_single_precise_owner():
    result = rows("responsable hse")
    assert result[0]["profession_id"] == "industry.responsable_hse"
    assert "industry.qualite" not in {r["profession_id"] for r in result}


def test_charge_publicite_exact_alias_has_single_precise_owner():
    result = rows("chargé de publicité")
    assert result[0]["profession_id"] == "sales.publicite"
    assert "sales.marketing" not in {r["profession_id"] for r in result}


def test_electricien_does_not_surface_estheticien_fuzzy_noise():
    assert "beauty.estheticien" not in ids("électricien")


def test_communication_does_not_match_inside_telecommunications():
    assert "it.telecom" not in ids("communication")


def test_generic_technicien_prefers_canonical_technician_labels():
    result = rows("technicien")
    assert result
    assert normalize(result[0]["label"]).startswith("technicien")


def test_generic_ingenieur_prefers_canonical_engineer_labels():
    result = rows("ingénieur")
    assert result
    assert normalize(result[0]["label"]).startswith("ingenieur")


def test_informatique_prefers_explicit_informatique_label():
    result = rows("informatique")
    assert result
    assert "informatique" in normalize(result[0]["label"])


def test_genie_civil_direct_professions_rank_before_trainer_alias():
    result_ids = ids("génie civil")
    assert "btp.ingenieur_genie_civil" in result_ids
    assert "btp.technicien_genie_civil" in result_ids

    if "edu.formateur_professionnel" in result_ids:
        trainer = result_ids.index("edu.formateur_professionnel")
        assert result_ids.index("btp.ingenieur_genie_civil") < trainer
        assert result_ids.index("btp.technicien_genie_civil") < trainer


def test_typo_fallback_still_finds_comptable():
    result = rows("comptablee")
    assert result
    assert result[0]["profession_id"] == "finance.comptable"


def test_developpement_informatique_keeps_legitimate_ambiguity():
    result_ids = ids("développement informatique")
    assert "it.developpeur_logiciel" in result_ids
    assert "it.technicien_developpement_informatique" in result_ids
