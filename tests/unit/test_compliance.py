from importlib.resources import files

import pytest
from pydantic import ValidationError

from bylaw.compliance import Profile, available, load_profile
from bylaw.model import Severity

# The development related Annex A 2022 controls the backlog asks for (CMP-2).
ISO27001_CONTROLS = {
    "5.34",
    "8.3",
    "8.4",
    "8.5",
    "8.8",
    "8.9",
    "8.11",
    "8.12",
    "8.15",
    "8.24",
    "8.25",
    "8.26",
    "8.27",
    "8.28",
    "8.29",
    "8.31",
    "8.32",
    "8.33",
}


def test_iso27001_ships_with_the_development_controls_of_annex_a_2022() -> None:
    profile = load_profile("iso27001")

    assert {control.id for control in profile.controls} == ISO27001_CONTROLS
    assert "27001:2022" in profile.standard


def test_every_control_has_a_short_title_and_guidance_of_bylaws_own() -> None:
    for control in load_profile("iso27001").controls:
        assert 0 < len(control.title) <= 50, control.id
        assert 40 < len(control.guidance) <= 400, control.id


def test_the_profile_file_says_the_standards_text_is_not_in_it() -> None:
    text = files("bylaw").joinpath("profiles/iso27001.toml").read_text(encoding="utf-8")
    header = text.split("\n\n", 1)[0]

    assert "copyright" in header.lower()
    assert "not" in header and "text" in header


def test_the_profiles_shipped_are_listed_by_name() -> None:
    assert "iso27001" in available()


def test_an_unknown_profile_is_refused_with_the_known_names() -> None:
    with pytest.raises(ValueError, match="iso27001"):
        load_profile("soc3")


def test_a_severity_rule_must_name_controls_the_profile_defines() -> None:
    with pytest.raises(ValidationError, match=r"9\.99"):
        Profile.model_validate(
            {
                "name": "x",
                "standard": "X",
                "controls": [{"id": "1.1", "title": "One", "guidance": "g"}],
                "severity_rules": [{"controls": ["9.99"], "minimum": "high", "why": "w"}],
            }
        )


def test_control_ids_are_unique_in_a_profile() -> None:
    with pytest.raises(ValidationError, match=r"1\.1"):
        Profile.model_validate(
            {
                "name": "x",
                "standard": "X",
                "controls": [
                    {"id": "1.1", "title": "One", "guidance": "g"},
                    {"id": "1.1", "title": "Again", "guidance": "g"},
                ],
            }
        )


def test_iso27001_raises_personal_data_in_logs_and_weak_cryptography_to_high() -> None:
    rules = {(rule.controls, rule.category, rule.minimum) for rule in load_profile("iso27001").severity_rules}

    assert (("8.15", "8.11"), None, Severity.HIGH) in rules
    assert (("8.24",), "security", Severity.HIGH) in rules
