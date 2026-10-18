import base64
import json
from collections.abc import Sequence

import httpx
import pytest
import respx

from bylaw.config import ConfigError, load_config
from bylaw.requirements import extract_criteria
from bylaw.trackers import (
    WorkItemRef,
    adf_markdown,
    html_markdown,
    parse_work_item_refs,
    read_work_items,
    with_criteria,
)

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


JIRA = "https://acme.atlassian.net"
JIRA_ENV = {"JIRA_EMAIL": "dev@acme.test", "JIRA_API_TOKEN": "jira-secret-token"}
JIRA_CONFIG = f'[jira]\nurl = "{JIRA}"\nprojects = ["PROJ"]\ncriteria_field = "customfield_10042"\n'
HIDDEN = (
    "Could not read {key} from {tracker}, or it is outside the allow list; "
    "it is left out of the requirement check."
)


def _text(text: str) -> dict[str, object]:
    return {"type": "text", "text": text}


def _paragraph(*parts: dict[str, object]) -> dict[str, object]:
    return {"type": "paragraph", "content": list(parts)}


def _list(kind: str, *items: str) -> dict[str, object]:
    return {
        "type": kind,
        "content": [{"type": "listItem", "content": [_paragraph(_text(item))]} for item in items],
    }


def _doc(*blocks: dict[str, object]) -> dict[str, object]:
    return {"type": "doc", "version": 1, "content": list(blocks)}


def _jira_issue(key: str = "PROJ-12", **fields: object) -> dict[str, object]:
    return {"key": key, "fields": {"summary": "Sign in with SSO", "description": None, **fields}}


def _notes_leak(notes: Sequence[str], env: dict[str, str]) -> bool:
    secrets = set(env.values()) | {
        base64.b64encode(f"{a}:{b}".encode()).decode() for a in env.values() for b in env.values()
    }
    return any(secret in note for note in notes for secret in secrets)


@respx.mock
def test_a_jira_issue_becomes_a_requirement_with_criteria_from_its_description() -> None:
    description = _doc(
        _paragraph(_text("Users sign in through the company identity provider.")),
        {"type": "heading", "attrs": {"level": 2}, "content": [_text("Acceptance criteria")]},
        _list("bulletList", "A user with an SSO account signs in", "A disabled account is refused"),
    )
    route = respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(200, json=_jira_issue(description=description))
    )

    requirements, notes = read_work_items(["PROJ-12: SSO"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert notes == ()
    [requirement] = requirements
    assert (requirement.source, requirement.title) == ("PROJ-12", "Sign in with SSO")
    assert [c.text for c in requirement.criteria] == [
        "A user with an SSO account signs in",
        "A disabled account is refused",
    ]
    assert not requirement.inferable
    request = route.calls.last.request
    assert request.url.params["fields"] == "summary,description,customfield_10042"
    expected = base64.b64encode(b"dev@acme.test:jira-secret-token").decode()
    assert request.headers["authorization"] == f"Basic {expected}"


@respx.mock
def test_action_items_ordered_lists_and_nested_lists_in_jira_text_become_markdown() -> None:
    description = _doc(
        {
            "type": "taskList",
            "attrs": {"localId": "t"},
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"localId": "a", "state": "TODO"},
                    "content": [_text("Log the sign-in")],
                },
                {
                    "type": "taskItem",
                    "attrs": {"localId": "b", "state": "DONE"},
                    "content": [_text("Keep the session")],
                },
            ],
        },
        {
            "type": "orderedList",
            "content": [
                {
                    "type": "listItem",
                    "content": [_paragraph(_text("Step one")), _list("bulletList", "nested point")],
                }
            ],
        },
        _paragraph(_text("Line one"), {"type": "hardBreak"}, _text("line two")),
        {"type": "codeBlock", "content": [_text("- [ ] not a criterion")]},
    )
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(200, json=_jira_issue(description=description))
    )

    [requirement], _ = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert requirement.text.splitlines()[:5] == [
        "- [ ] Log the sign-in",
        "- [x] Keep the session",
        "",
        "1. Step one",
        "  - nested point",
    ]
    assert [c.text for c in requirement.criteria] == ["Log the sign-in", "Keep the session"]


@pytest.mark.parametrize(
    "field",
    [
        _doc(_paragraph(_text("Refuses an expired token")), _paragraph(_text("Logs every refusal"))),
        "Refuses an expired token\nLogs every refusal",
    ],
    ids=["rich text field", "plain text field"],
)
@respx.mock
def test_each_line_of_the_jira_criteria_field_is_a_criterion(field: object) -> None:
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(200, json=_jira_issue(customfield_10042=field))
    )

    [requirement], _ = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert [c.text for c in requirement.criteria] == ["Refuses an expired token", "Logs every refusal"]


@respx.mock
def test_a_jira_issue_written_as_prose_may_get_inferred_criteria() -> None:
    description = _doc(_paragraph(_text("Make sign-in faster.")))
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(200, json=_jira_issue(description=description))
    )

    [requirement], notes = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert (requirement.criteria, requirement.inferable) == ((), True)
    assert notes == ("PROJ-12 has no structured acceptance criteria.",)


@respx.mock
def test_a_jira_issue_moved_to_a_project_outside_the_allow_list_is_left_out() -> None:
    # Jira answers a moved issue's old key with the issue under its new key, not with a redirect.
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(
            200, json=_jira_issue("SECRET-4", description=_doc(_paragraph(_text("x"))))
        )
    )

    requirements, notes = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert requirements == ()
    assert "PROJ-12" in notes[0] and "SECRET" not in notes[0]


@respx.mock
def test_jira_is_not_called_without_its_credentials() -> None:
    route = respx.get(url__startswith=JIRA)

    requirements, notes = read_work_items(
        ["PROJ-12"], load_config(JIRA_CONFIG), {"JIRA_EMAIL": "dev@acme.test"}
    )

    assert requirements == ()
    assert not route.called
    assert notes == ("JIRA_EMAIL and JIRA_API_TOKEN are not set, so PROJ-12 was not read from Jira.",)


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(404, json={"errorMessages": ["Issue does not exist"]}),
        httpx.Response(401, text="unauthorised"),
        httpx.Response(500),
        httpx.Response(200, text="<html>login</html>"),
        httpx.ConnectError("connection refused"),
    ],
    ids=["missing", "bad token", "server error", "not json", "network error"],
)
@respx.mock
def test_an_unreadable_jira_issue_is_a_note_and_the_review_goes_on(
    answer: httpx.Response | Exception,
) -> None:
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(side_effect=[answer])

    requirements, notes = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert requirements == ()
    assert len(notes) == 1 and notes[0].startswith("Could not read PROJ-12 from Jira")
    assert not _notes_leak(notes, JIRA_ENV)


@respx.mock
def test_a_redirect_is_not_followed_with_the_credentials() -> None:
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(302, headers={"Location": "https://evil.test/steal"})
    )
    elsewhere = respx.get(url__startswith="https://evil.test")

    requirements, notes = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert requirements == ()
    assert not elsewhere.called
    assert "redirect" in notes[0]


@respx.mock
def test_a_pull_request_naming_many_work_items_reads_only_the_first_ten() -> None:
    route = respx.get(url__startswith=f"{JIRA}/rest/api/3/issue/").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=_jira_issue(request.url.path.rsplit("/", 1)[-1], description=_doc(_paragraph(_text("x")))),
        )
    )

    requirements, notes = read_work_items(
        [" ".join(f"PROJ-{n}" for n in range(1, 13))], load_config(JIRA_CONFIG), JIRA_ENV
    )

    assert route.call_count == 10
    assert len(requirements) == 10
    assert notes[0] == "12 work items are referenced; only the first 10 are read. Left out: PROJ-11, PROJ-12."


AZURE = "https://dev.azure.com/acme/_apis/wit/workitems"
AZURE_ENV = {"AZURE_DEVOPS_TOKEN": "azure-secret-pat"}
AZURE_CONFIG = '[azure_boards]\norganization = "acme"\nprojects = ["Fabrikam"]\n'


def _work_item(project: str = "Fabrikam", **fields: object) -> dict[str, object]:
    return {"id": 345, "fields": {"System.TeamProject": project, "System.Title": "Export to CSV", **fields}}


@respx.mock
def test_an_azure_boards_work_item_becomes_a_requirement_with_its_acceptance_criteria_field() -> None:
    route = respx.get(f"{AZURE}/345").mock(
        return_value=httpx.Response(
            200,
            json=_work_item(
                **{
                    "System.Description": "<div>Finance needs the report as a file.</div>",
                    "Microsoft.VSTS.Common.AcceptanceCriteria": (
                        "<div>Exports every visible column</div><div>Keeps the sort order&nbsp;</div>"
                    ),
                }
            ),
        )
    )

    requirements, notes = read_work_items(["Implements AB#345"], load_config(AZURE_CONFIG), AZURE_ENV)

    assert notes == ()
    [requirement] = requirements
    assert (requirement.source, requirement.title) == ("AB#345", "Export to CSV")
    assert [c.text for c in requirement.criteria] == ["Exports every visible column", "Keeps the sort order"]
    assert requirement.text.startswith("Finance needs the report as a file.")
    request = route.calls.last.request
    assert request.url.params["api-version"] == "7.1"
    expected = base64.b64encode(b":azure-secret-pat").decode()
    assert request.headers["authorization"] == f"Basic {expected}"


def test_html_from_azure_boards_keeps_its_lists_and_headings() -> None:
    html = (
        "<h2>Acceptance criteria</h2><ol><li>One &amp; two</li><li><p>Three</p><ul><li>nested</li></ul></li>"
        "</ol><p>Plain<br>text <b>bold</b></p><script>alert(1)</script>"
    )

    assert html_markdown(html).splitlines() == [
        "## Acceptance criteria",
        "1. One & two",
        "2. Three",
        "  - nested",
        "Plain",
        "text bold",
    ]


@respx.mock
def test_a_work_item_in_a_project_outside_the_allow_list_is_left_out() -> None:
    respx.get(f"{AZURE}/345").mock(
        return_value=httpx.Response(200, json=_work_item("Secret", **{"System.Description": "x"}))
    )

    requirements, notes = read_work_items(["AB#345"], load_config(AZURE_CONFIG), AZURE_ENV)

    assert requirements == ()
    assert notes == (HIDDEN.format(key="AB#345", tracker="Azure Boards"),)


@respx.mock
def test_azure_project_names_match_without_case() -> None:
    respx.get(f"{AZURE}/345").mock(
        return_value=httpx.Response(200, json=_work_item("fabrikam", **{"System.Description": "- [ ] x"}))
    )

    requirements, _ = read_work_items(["AB#345"], load_config(AZURE_CONFIG), AZURE_ENV)

    assert [r.source for r in requirements] == ["AB#345"]


@respx.mock
def test_azure_boards_is_not_called_without_a_token() -> None:
    route = respx.get(url__startswith="https://dev.azure.com")

    requirements, notes = read_work_items(["AB#345"], load_config(AZURE_CONFIG), {})

    assert (requirements, route.called) == ((), False)
    assert notes == ("AZURE_DEVOPS_TOKEN is not set, so AB#345 was not read from Azure Boards.",)


@respx.mock
def test_an_unreadable_work_item_is_a_note_that_never_shows_the_token() -> None:
    respx.get(f"{AZURE}/345").mock(return_value=httpx.Response(203, text="<html>sign in</html>"))

    requirements, notes = read_work_items(["AB#345"], load_config(AZURE_CONFIG), AZURE_ENV)

    assert requirements == ()
    assert notes == (
        "Could not read AB#345 from Azure Boards (HTTP 203); it is left out of the requirement check.",
    )
    assert not _notes_leak(notes, AZURE_ENV)


LINEAR = "https://api.linear.app/graphql"
LINEAR_ENV = {"LINEAR_API_KEY": "lin_api_secret"}
LINEAR_CONFIG = '[linear]\nteams = ["ENG"]\n'


def _linear_issue(team: str = "ENG", description: str | None = "- [ ] Sends a welcome email") -> object:
    issue = {
        "identifier": "ENG-7",
        "title": "Welcome email",
        "description": description,
        "team": {"key": team},
    }
    return {"data": {"issue": issue}}


@respx.mock
def test_a_linear_issue_becomes_a_requirement_with_criteria_from_its_markdown() -> None:
    route = respx.post(LINEAR).mock(return_value=httpx.Response(200, json=_linear_issue()))

    requirements, notes = read_work_items(["ENG-7"], load_config(LINEAR_CONFIG), LINEAR_ENV)

    assert notes == ()
    [requirement] = requirements
    assert (requirement.source, requirement.title) == ("ENG-7", "Welcome email")
    assert [c.text for c in requirement.criteria] == ["Sends a welcome email"]
    request = route.calls.last.request
    # A personal API key goes in the header as it is, without "Bearer".
    assert request.headers["authorization"] == "lin_api_secret"
    body = json.loads(request.content)
    assert body["variables"] == {"id": "ENG-7"}
    assert "issue(id: $id)" in body["query"]


@respx.mock
def test_a_linear_issue_moved_to_a_team_outside_the_allow_list_is_left_out() -> None:
    respx.post(LINEAR).mock(return_value=httpx.Response(200, json=_linear_issue(team="SEC")))

    requirements, notes = read_work_items(["ENG-7"], load_config(LINEAR_CONFIG), LINEAR_ENV)

    assert requirements == ()
    assert notes == (HIDDEN.format(key="ENG-7", tracker="Linear"),)


@respx.mock
def test_a_linear_error_answer_is_a_note_without_the_api_message() -> None:
    answer = {"data": None, "errors": [{"message": "Entity not found: lin_api_secret"}]}
    respx.post(LINEAR).mock(return_value=httpx.Response(200, json=answer))

    requirements, notes = read_work_items(["ENG-7"], load_config(LINEAR_CONFIG), LINEAR_ENV)

    assert requirements == ()
    assert notes == (HIDDEN.format(key="ENG-7", tracker="Linear"),)
    assert not _notes_leak(notes, LINEAR_ENV)


@respx.mock
def test_linear_is_not_called_without_an_api_key() -> None:
    route = respx.post(LINEAR)

    requirements, notes = read_work_items(["ENG-7"], load_config(LINEAR_CONFIG), {"LINEAR_API_KEY": ""})

    assert (requirements, route.called) == ((), False)
    assert notes == ("LINEAR_API_KEY is not set, so ENG-7 was not read from Linear.",)


@pytest.mark.parametrize(("setting", "quoted"), [("", True), ("quote_trackers = false\n", False)])
@respx.mock
def test_quote_trackers_decides_whether_work_item_text_may_be_quoted(setting: str, quoted: bool) -> None:
    respx.post(LINEAR).mock(return_value=httpx.Response(200, json=_linear_issue()))

    [requirement], _ = read_work_items(["ENG-7"], load_config(setting + LINEAR_CONFIG), LINEAR_ENV)

    assert requirement.quoted is quoted
    # The reviewer still reads the text: only the public summary leaves it out.
    assert requirement.text == "- [ ] Sends a welcome email"


@respx.mock
def test_work_items_named_by_an_untrusted_author_are_not_read() -> None:
    route = respx.post(LINEAR)

    requirements, notes = read_work_items(
        ["ENG-7"], load_config(LINEAR_CONFIG), LINEAR_ENV, author_trusted=False
    )

    assert (requirements, route.called) == ((), False)
    assert notes == (
        "ENG-7 was not read: the pull request author is not an owner, member or collaborator. "
        "trackers_for_all_authors = true in .bylaw.toml reads work items for every author.",
    )


@respx.mock
def test_trackers_for_all_authors_reads_work_items_for_any_author() -> None:
    respx.post(LINEAR).mock(return_value=httpx.Response(200, json=_linear_issue()))
    config = load_config("trackers_for_all_authors = true\n" + LINEAR_CONFIG)

    requirements, _ = read_work_items(["ENG-7"], config, LINEAR_ENV, author_trusted=False)

    assert [r.source for r in requirements] == ["ENG-7"]


def _criteria_of(markdown: str) -> list[str]:
    return [c.text for c in extract_criteria(markdown)]


def test_a_code_block_that_opens_a_jira_list_item_does_not_swallow_later_criteria() -> None:
    doc = _doc(
        {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [{"type": "codeBlock", "content": [_text("make test")]}]},
            ],
        },
        {
            "type": "taskList",
            "content": [
                {"type": "taskItem", "attrs": {"state": "TODO"}, "content": [_text("Later criterion")]}
            ],
        },
    )

    assert _criteria_of(adf_markdown(doc)) == ["Later criterion"]


def test_a_hard_break_or_second_paragraph_in_a_jira_list_item_stays_in_one_criterion() -> None:
    doc = _doc(
        {"type": "heading", "attrs": {"level": 2}, "content": [_text("Acceptance criteria")]},
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        _paragraph(_text("Exports a file"), {"type": "hardBreak"}, _text("named by date")),
                        _paragraph(_text("in UTF-8")),
                        _list("bulletList", "nested point"),
                    ],
                }
            ],
        },
    )

    assert _criteria_of(adf_markdown(doc)) == ["Exports a file named by date in UTF-8", "nested point"]


def test_html_pre_blocks_are_fenced_and_keep_their_lines() -> None:
    html = "<pre>- [ ] not a criterion\nsecond line</pre><ul><li>Real criterion</li></ul>"

    markdown = html_markdown(html)

    assert markdown.splitlines()[:4] == ["```", "- [ ] not a criterion", "second line", "```"]
    assert _criteria_of("## Acceptance criteria\n" + markdown) == ["Real criterion"]


def test_html_table_cells_are_separated_so_given_when_then_tables_survive() -> None:
    html = (
        "<table><tr><td>Given</td><td>a signed in user</td></tr>"
        "<tr><td>When</td><td>they export</td></tr><tr><th>Then</th><th>a file downloads</th></tr></table>"
    )

    assert _criteria_of(html_markdown(html)) == [
        "Given a signed in user When they export Then a file downloads"
    ]


def test_an_html_list_item_with_breaks_or_paragraphs_stays_one_criterion() -> None:
    html = (
        "<h2>Acceptance criteria</h2>"
        "<ul><li>Exports a file<br>named by date<p>in UTF-8</p></li><li>Two</li></ul>"
    )

    assert _criteria_of(html_markdown(html)) == ["Exports a file named by date in UTF-8", "Two"]


def test_lines_inside_a_code_fence_of_a_criteria_field_are_not_criteria() -> None:
    field = "Refuses an expired token\n```\nexample: curl -X POST\nanother line\n```\nLogs every refusal"

    assert _criteria_of(with_criteria("", field)) == ["Refuses an expired token", "Logs every refusal"]


@respx.mock
def test_a_token_an_http_header_cannot_carry_is_a_note_not_a_crash() -> None:
    route = respx.post(LINEAR)
    env = {"LINEAR_API_KEY": "lin_api_secret\u2019"}  # a curly quote pasted with the key

    requirements, notes = read_work_items(["ENG-7"], load_config(LINEAR_CONFIG), env)

    assert (requirements, route.called) == ((), False)
    assert notes == (
        "Could not read ENG-7 from Linear (the token has characters an HTTP header cannot carry); "
        "it is left out of the requirement check.",
    )
    assert not _notes_leak(notes, env)


def test_a_token_put_in_the_config_is_not_echoed_and_must_be_rotated() -> None:
    text = f'[jira]\nurl = "{JIRA}"\nprojects = ["PROJ"]\napi_token = "SECRET123"\n'

    with pytest.raises(ConfigError) as caught:
        load_config(text)

    assert "SECRET123" not in str(caught.value)
    assert "rotate" in str(caught.value)


def test_no_config_error_echoes_the_value_it_rejects() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config('max_comments = "SECRET123"\n')

    assert "SECRET123" not in str(caught.value)


@respx.mock
def test_a_missing_jira_issue_and_one_outside_the_allow_list_get_the_same_note() -> None:
    route = respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12")
    config = load_config(JIRA_CONFIG)

    route.mock(return_value=httpx.Response(404, json={"errorMessages": ["Issue does not exist"]}))
    _, missing = read_work_items(["PROJ-12"], config, JIRA_ENV)
    route.mock(return_value=httpx.Response(200, json=_jira_issue("SECRET-4")))
    _, moved = read_work_items(["PROJ-12"], config, JIRA_ENV)

    assert missing == moved == (HIDDEN.format(key="PROJ-12", tracker="Jira"),)


@respx.mock
def test_a_missing_work_item_and_one_in_an_unlisted_project_get_the_same_note() -> None:
    route = respx.get(f"{AZURE}/345")
    config = load_config(AZURE_CONFIG)

    route.mock(return_value=httpx.Response(404))
    _, missing = read_work_items(["AB#345"], config, AZURE_ENV)
    route.mock(return_value=httpx.Response(200, json=_work_item("Secret")))
    _, unlisted = read_work_items(["AB#345"], config, AZURE_ENV)

    assert missing == unlisted == (HIDDEN.format(key="AB#345", tracker="Azure Boards"),)


@respx.mock
def test_a_missing_linear_issue_and_one_in_an_unlisted_team_get_the_same_note() -> None:
    route = respx.post(LINEAR)
    config = load_config(LINEAR_CONFIG)

    route.mock(
        return_value=httpx.Response(200, json={"data": None, "errors": [{"message": "Entity not found"}]})
    )
    _, missing = read_work_items(["ENG-7"], config, LINEAR_ENV)
    route.mock(return_value=httpx.Response(200, json=_linear_issue(team="SEC")))
    _, moved = read_work_items(["ENG-7"], config, LINEAR_ENV)

    assert missing == moved == (HIDDEN.format(key="ENG-7", tracker="Linear"),)
