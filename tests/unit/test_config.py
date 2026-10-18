import pytest

from bylaw.config import ConfigError, load_config
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
