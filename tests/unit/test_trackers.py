import pytest

from bylaw.config import ConfigError, load_config
from bylaw.trackers import WorkItemRef, parse_work_item_refs

TRACKERS = """
[jira]
url = "https://acme.atlassian.net"
projects = ["PROJ", "OPS"]

[azure_boards]
organization = "acme"
projects = ["Fabrikam"]

[linear]
teams = ["ENG"]
"""


def test_allowed_keys_in_the_title_body_and_commits_become_work_item_refs() -> None:
    config = load_config(TRACKERS)

    refs = parse_work_item_refs(
        ["PROJ-12: add login", "Implements AB#345 and ENG-7.", "fix: OPS-3 timeout\n\nAlso PROJ-12"], config
    )

    assert refs == (
        WorkItemRef("jira", "PROJ-12"),
        WorkItemRef("azure_boards", "AB#345"),
        WorkItemRef("linear", "ENG-7"),
        WorkItemRef("jira", "OPS-3"),
    )


def test_look_alikes_and_keys_outside_the_allow_list_are_not_references() -> None:
    config = load_config(TRACKERS)

    refs = parse_work_item_refs(
        ["Use UTF-8, SHA-256 and ISO-27001.", "See OTHER-5, proj-9, XPROJ-4, PROJ-0 and PROJ-12a."], config
    )

    assert refs == ()


def test_references_in_urls_and_branch_names_count() -> None:
    config = load_config(TRACKERS)

    refs = parse_work_item_refs(
        ["https://acme.atlassian.net/browse/PROJ-8", "Merge branch 'feature/ENG-2-signup'"], config
    )

    assert refs == (WorkItemRef("jira", "PROJ-8"), WorkItemRef("linear", "ENG-2"))


def test_nothing_is_a_reference_without_a_tracker_in_the_config() -> None:
    assert parse_work_item_refs(["PROJ-12 and AB#3 and ENG-7"], load_config(None)) == ()


def test_azure_boards_references_need_azure_boards_in_the_config() -> None:
    config = load_config('[linear]\nteams = ["ENG"]\n')

    assert parse_work_item_refs(["AB#3 and ENG-7"], config) == (WorkItemRef("linear", "ENG-7"),)


@pytest.mark.parametrize(
    "text",
    [
        '[jira]\nurl = "http://acme.atlassian.net"\nprojects = ["PROJ"]\n',
        '[jira]\nurl = "https://user:pw@acme.atlassian.net"\nprojects = ["PROJ"]\n',
        '[jira]\nurl = "https://acme.atlassian.net?x=1"\nprojects = ["PROJ"]\n',
        '[jira]\nurl = "https://acme.atlassian.net"\nprojects = []\n',
        '[jira]\nurl = "https://acme.atlassian.net"\nprojects = ["proj"]\n',
        '[jira]\nurl = "https://acme.atlassian.net"\nprojects = ["PROJ"]\ncriteria_field = "summary"\n',
        '[azure_boards]\norganization = "acme/other"\nprojects = ["Fabrikam"]\n',
        '[linear]\nteams = ["ENG"]\n[jira]\nurl = "https://acme.atlassian.net"\nprojects = ["ENG"]\n',
        '[jira]\nurl = "https://acme.atlassian.net"\nprojects = ["PROJ"]\napi_token = "secret"\n',
    ],
    ids=[
        "plain http",
        "credentials in the url",
        "query in the url",
        "empty allow list",
        "lower case key",
        "criteria field that is not a custom field",
        "organisation with a path",
        "key claimed by two trackers",
        "token in the config",
    ],
)
def test_a_tracker_setting_that_could_widen_the_reach_is_a_config_error(text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(text)


def test_the_jira_url_loses_its_trailing_slash() -> None:
    config = load_config('[jira]\nurl = "https://acme.atlassian.net/"\nprojects = ["PROJ"]\n')

    assert config.jira is not None
    assert config.jira.url == "https://acme.atlassian.net"
