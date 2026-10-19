import pytest

from bylaw import config as config_module
from bylaw.config import ConfigError, deprecations, load_config
from bylaw.model import Severity

ORG = """
severity_threshold = "high"
max_comments = 5
issue_repos = ["acme/roadmap"]

[jira]
url = "https://acme.atlassian.net"
projects = ["ACME"]
"""


def test_organisation_defaults_apply_where_the_repository_sets_nothing() -> None:
    config = load_config(None, defaults=ORG)

    assert (config.severity_threshold, config.max_comments, config.issue_repos) == (
        Severity.HIGH,
        5,
        ("acme/roadmap",),
    )


def test_a_key_the_repository_sets_overrides_the_organisation_default() -> None:
    config = load_config("max_comments = 20\nissue_repos = []\n", defaults=ORG)

    assert (config.severity_threshold, config.max_comments, config.issue_repos) == (Severity.HIGH, 20, ())


def test_a_table_the_repository_sets_replaces_the_organisation_table_whole() -> None:
    repo = '[jira]\nurl = "https://other.atlassian.net"\nprojects = ["OTHER"]\n'

    jira = load_config(repo, defaults=ORG).jira

    assert jira is not None
    assert (jira.url, jira.projects, jira.criteria_field) == ("https://other.atlassian.net", ("OTHER",), None)


def test_no_files_at_all_is_the_default_configuration() -> None:
    assert load_config(None, defaults=None) == load_config(None)


def test_an_invalid_organisation_file_is_named_in_the_error() -> None:
    with pytest.raises(ConfigError, match=r"organisation's \.bylaw\.toml in its \.github repository"):
        load_config(None, defaults="max_comments = 500\n")


def test_an_unparsable_organisation_file_is_named_in_the_error() -> None:
    with pytest.raises(ConfigError, match="organisation's"):
        load_config("max_comments = 3\n", defaults="max_comments = = 3\n")


def test_an_invalid_repository_file_is_still_named_as_the_base_branch() -> None:
    with pytest.raises(ConfigError, match=r"\.bylaw\.toml on the base branch is invalid"):
        load_config("max_comments = 500\n", defaults=ORG)


def test_the_app_reviews_only_trusted_same_repository_pull_requests_with_the_model_by_default() -> None:
    assert (load_config(None).app.model_review, load_config(None).app.model_review_label) == ("trusted", None)


def test_the_app_settings_can_open_the_model_review_to_all_or_to_a_label() -> None:
    config = load_config('[app]\nmodel_review = "all"\nmodel_review_label = "bylaw: review"\n')

    assert (config.app.model_review, config.app.model_review_label) == ("all", "bylaw: review")


def test_an_unknown_app_model_review_value_is_refused() -> None:
    with pytest.raises(ConfigError, match="base branch is invalid"):
        load_config('[app]\nmodel_review = "everyone"\n')


def test_a_compliance_profile_is_switched_on_by_name() -> None:
    assert load_config('profiles = ["iso27001"]\n').profiles == ("iso27001",)


def test_no_profile_is_on_by_default() -> None:
    assert load_config(None).profiles == ()


def test_an_unknown_profile_is_a_config_error_that_names_the_known_ones() -> None:
    with pytest.raises(ConfigError, match="iso27001"):
        load_config('profiles = ["iso27002"]\n')


def test_a_profile_named_twice_counts_once() -> None:
    assert load_config('profiles = ["iso27001", "iso27001"]\n').profiles == ("iso27001",)


def test_a_repository_cannot_drop_a_profile_the_organisation_turned_on() -> None:
    # ADR 0021: profiles are a floor; every other key the repository sets replaces the organisation's.
    config = load_config("profiles = []\nmax_comments = 3\n", defaults='profiles = ["iso27001"]\n')

    assert (config.profiles, config.max_comments) == (("iso27001",), 3)


def test_a_configuration_without_a_version_is_version_1() -> None:
    # Every .bylaw.toml written for 0.x has no version, and must mean what it always meant (ADR 0023).
    assert load_config(None).version == 1
    assert load_config("version = 1\n").version == 1


def test_an_unknown_configuration_version_fails_and_names_the_versions_bylaw_reads() -> None:
    with pytest.raises(ConfigError, match=r"says version 2.*reads version 1"):
        load_config("version = 2\n")


def test_an_organisation_default_with_an_unknown_version_names_the_organisation_file() -> None:
    with pytest.raises(ConfigError, match=r"(?s)^The organisation's .bylaw.toml .*says version 3"):
        load_config(None, defaults="version = 3\n")


def test_a_version_that_is_not_a_number_is_refused_without_repeating_it() -> None:
    with pytest.raises(ConfigError) as raised:
        load_config('version = "ghp_pasted_in_the_wrong_place"\n')

    assert "ghp_pasted" not in str(raised.value)


def test_a_deprecated_key_keeps_working_and_gives_a_note_that_says_what_replaces_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No key is deprecated yet, so two live ones stand in, one of them inside a table (docs/compatibility.md).
    dummy = {"max_comments": "Use `dummy_limit` instead.", "app.model_review": "Use `dummy_gate` instead."}
    monkeypatch.setattr(config_module, "DEPRECATED_KEYS", dummy)

    config = load_config('max_comments = 3\n[app]\nmodel_review = "all"\n')

    assert (config.max_comments, config.app.model_review) == (3, "all")
    assert deprecations(config) == (
        "Deprecated: `max_comments` in .bylaw.toml still works, but goes in the next major release. "
        "Use `dummy_limit` instead.",
        "Deprecated: `app.model_review` in .bylaw.toml still works, but goes in the next major release. "
        "Use `dummy_gate` instead.",
    )
    assert deprecations(load_config('[app]\nmodel_review_label = "x"\n')) == ()


def test_learning_is_off_by_default() -> None:
    learn = load_config(None).learn

    assert (learn.enabled, learn.threshold, learn.suggest) == (False, 3, ("rule",))


def test_learning_is_switched_on_with_a_threshold_and_the_categories_it_may_suggest() -> None:
    learn = load_config('[learn]\nenabled = true\nthreshold = 5\nsuggest = ["rule", "bug"]\n').learn

    assert (learn.enabled, learn.threshold, learn.suggest) == (True, 5, ("rule", "bug"))


def test_learning_may_never_suggest_hiding_security_findings() -> None:
    # ADR 0022: a security finding is never suggested for suppression, whatever the maintainers did.
    with pytest.raises(ConfigError, match=r"learn.suggest"):
        load_config('[learn]\nenabled = true\nsuggest = ["security"]\n')


def test_a_threshold_of_one_pull_request_is_refused() -> None:
    # One mute is a decision about one change, not a pattern.
    with pytest.raises(ConfigError, match=r"learn.threshold"):
        load_config("[learn]\nthreshold = 1\n")


SUPPRESS = """
[[suppress]]
rule = "ruff:S101"
paths = ["tests/**"]
reason = "Tests use assert."
"""


def test_a_suppression_names_the_rule_the_paths_and_why() -> None:
    (suppression,) = load_config(SUPPRESS).suppress

    assert (suppression.rule, suppression.paths, suppression.reason) == (
        "ruff:S101",
        ("tests/**",),
        "Tests use assert.",
    )


def test_a_suppression_without_paths_covers_every_file() -> None:
    (suppression,) = load_config('[[suppress]]\nrule = "ruff:S101"\nreason = "r"\n').suppress

    assert suppression.paths == ("**",)


@pytest.mark.parametrize(
    "text",
    [
        '[[suppress]]\nrule = "ruff:S101"\n',
        '[[suppress]]\nrule = ""\nreason = "r"\n',
        '[[suppress]]\nrule = "ruff:S101"\nreason = "r"\npaths = []\n',
        '[[suppress]]\nrule = "ruff:S101"\nreason = "r"\ncategory = "security"\n',
    ],
)
def test_a_suppression_without_a_reason_a_rule_or_a_path_or_with_an_unknown_key_is_refused(text: str) -> None:
    with pytest.raises(ConfigError, match=r"suppress\.0"):
        load_config(text)
