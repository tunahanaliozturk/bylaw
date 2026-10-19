from bylaw.config import load_config
from bylaw.github import PullRequest
from bylaw.pull_review import APP_PR_TOKENS, model_gate, with_app_budget


def _pull(
    association: str = "MEMBER", head: str | None = "acme/app", labels: tuple[str, ...] = ()
) -> PullRequest:
    return PullRequest.model_validate(
        {
            "title": "t",
            "author_association": association,
            "base": {"sha": "b", "repo": {"full_name": "acme/app"}},
            "head": {"sha": "h", "repo": None if head is None else {"full_name": head}},
            "labels": [{"name": name} for name in labels],
        }
    )


def test_the_app_caps_a_pull_request_s_tokens_when_the_repository_sets_no_cap() -> None:
    assert with_app_budget(load_config(None)).budget.pr_tokens == APP_PR_TOKENS


def test_a_cap_the_repository_sets_is_kept() -> None:
    assert with_app_budget(load_config("[budget]\npr_tokens = 2000000\n")).budget.pr_tokens == 2_000_000


def test_owners_members_and_collaborators_branches_pass_the_gate_case_aside() -> None:
    for association in ("OWNER", "MEMBER", "COLLABORATOR"):
        assert model_gate(_pull(association, head="ACME/App"), load_config(None)) is None


def test_forks_and_other_authors_are_held_back_unless_a_label_or_the_setting_lets_them_in() -> None:
    labelled = load_config('[app]\nmodel_review_label = "bylaw: review"\n')

    assert model_gate(_pull(head="stranger/app"), load_config(None)) is not None
    assert model_gate(_pull("FIRST_TIME_CONTRIBUTOR"), load_config(None)) is not None
    assert model_gate(_pull(head="stranger/app", labels=("other",)), labelled) is not None
    assert model_gate(_pull(head="stranger/app", labels=("bylaw: review",)), labelled) is None
    assert model_gate(_pull(head=None), load_config('[app]\nmodel_review = "all"\n')) is None


def test_under_a_trusted_ceiling_the_gate_does_not_suggest_opening_the_review_to_all() -> None:
    config = load_config('[app]\nmodel_review = "all"\n', defaults='[ceiling]\nmodel_review = "trusted"\n')

    why = model_gate(_pull(head="stranger/app"), config)

    assert why is not None
    assert 'model_review = "all"' not in why
    assert "organisation's `[ceiling]`" in why
