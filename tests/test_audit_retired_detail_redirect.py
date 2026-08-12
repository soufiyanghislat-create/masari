from audit import _detail_gate_state


def test_detail_gate_passes_when_every_resolvable_detail_is_parsed():
    good = "https://www.emploi-public.ma/fr/concours/details/good"
    retired = "https://www.emploi-public.ma/fr/concours/details/retired"

    gate, resolvable, missing, invalid_retired = _detail_gate_state(
        expected_urls={good, retired},
        parsed_urls={good},
        retired_redirects={
            retired: "https://www.emploi-public.ma/fr/concours-liste"
        },
        failures={},
    )

    assert gate is True
    assert resolvable == {good}
    assert missing == []
    assert invalid_retired == []


def test_detail_gate_still_fails_on_real_detail_failure():
    good = "https://www.emploi-public.ma/fr/concours/details/good"

    gate, _, missing, _ = _detail_gate_state(
        expected_urls={good},
        parsed_urls=set(),
        retired_redirects={},
        failures={good: "ValueError: Missing administration"},
    )

    assert gate is False
    assert missing == [good]
