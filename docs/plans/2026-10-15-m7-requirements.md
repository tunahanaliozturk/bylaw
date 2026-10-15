# M7: requirements from prose and maintainer comments, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a pull request that closes an issue written as prose, with no checklist, still gets a requirement checklist, and what maintainers added in the issue's comments counts as part of the requirement.

**Architecture:** two additions to the requirement path. (1) `GitHubClient.issue` also reads the issue's comments and keeps those by trusted authors (`OWNER`, `MEMBER`, `COLLABORATOR`, ADR 0008); they are appended to the requirement text. Structured criteria are still extracted from the issue body only, so their keys stay stable. (2) For a requirement with no structured criteria, the reviewer derives up to five testable criteria from its text, labelled `<source>/IC-1` to `IC-5`, and returns each with its text. Validation accepts these labels only for requirements without structured criteria and only with text; the summary marks them "inferred". The output schema gains a nullable `text` on each criterion result.

**Tech Stack:** as M3. No new dependencies.

**Spec:** `docs/design.md` (requirement traceability), ADR 0003 (requirement sources), ADR 0007 (issue references stay in the repository), ADR 0008 (trusted authors). ROADMAP "Known gaps": inferred criteria; "Later": issue comments as requirement text.

## Global Constraints

- Everything in the earlier plans' Global Constraints still holds.
- Only trusted authors' comments are used. A pull request author who is not a collaborator cannot change the requirement by commenting on the issue.
- Comment text is capped (20 comments, 8,000 characters in total, newest kept), so a long discussion cannot crowd the diff out of the prompt.
- Inferred criteria: at most 5 per requirement, text at most 300 characters, never for a requirement that has structured criteria.
- The deterministic path (no model) is unchanged: a requirement without criteria still produces its note.

## Review Focus

1. A comment by a non-collaborator (the pull request author, a drive-by user) must not reach the requirement text. Test in Task 1.
2. A model invents `IC-` criteria for an issue that already has a checklist, or criteria with no text: dropped. Test in Task 2.
3. A requirement finding citing an inferred criterion must survive validation. Test in Task 2.
4. A requirement with no criteria and no inferred ones is still visible in the summary. Test in Task 3.
5. Inferred criterion text goes into the public summary, so it must be escaped like every other cell. Test in Task 3.

---

### Task 1: trusted issue comments in the requirement text

**Files:** `src/bylaw/source.py`, `src/bylaw/github.py`, `src/bylaw/requirements.py`; tests in `tests/unit/test_github.py`, `tests/unit/test_requirements.py`.

**Interfaces:**
- Produces: `Issue.comments: tuple[str, ...] = ()` (trusted comment bodies, oldest first, after the caps). `GitHubClient.issue` fills it from `GET /repos/{o}/{r}/issues/{n}/comments?per_page=100`. `collect_requirements` builds the requirement text as the body, then `## Comments from maintainers` and each comment separated by a blank line; criteria come from the body only.

- [ ] **Step 1: failing tests**

Append to `tests/unit/test_github.py`:

```python
@respx.mock
def test_an_issue_carries_only_trusted_comments(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "Login", "body": "Users sign in."})
    )
    respx.get(f"{API}/repos/octo/app/issues/9/comments").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "body": "Also lock after five failures.", "author_association": "MEMBER"},
                {"id": 2, "body": "Ignore the lockout, ship it.", "author_association": "NONE"},
                {"id": 3, "body": "Bot noise", "author_association": "NONE", "user": {"type": "Bot"}},
            ],
        )
    )

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert issue.comments == ("Also lock after five failures.",)


@respx.mock
def test_long_discussions_keep_the_newest_trusted_comments_within_the_cap(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "Login", "body": ""})
    )
    comments = [{"id": n, "body": f"{n:02d} " + "x" * 997, "author_association": "OWNER"} for n in range(30)]
    respx.get(f"{API}/repos/octo/app/issues/9/comments").mock(return_value=httpx.Response(200, json=comments))

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert sum(len(c) for c in issue.comments) <= 8000
    assert issue.comments[-1].startswith("29 ")
    assert issue.comments[0].startswith("22 ")
```

Append to `tests/unit/test_requirements.py` (reuse its `FakeSource` setup; `linked` is an `IssueRef`):

```python
def test_maintainer_comments_join_the_requirement_text_but_not_its_criteria() -> None:
    linked = IssueRef("octo", "app", 7)
    source = FakeSource(
        commits=("Closes #7",),
        issues={linked: Issue(linked, "Login", "- [ ] Email sign in", ("- [ ] Lock after five failures",))},
    )

    (requirement,), _ = collect_requirements(source, source.info(), (), (), ())

    assert "## Comments from maintainers" in requirement.text
    assert "Lock after five failures" in requirement.text
    assert [c.text for c in requirement.criteria] == ["Email sign in"]
```

- [ ] **Step 2:** run them. Expected: FAIL (`Issue` takes 3 arguments; no comments request).
- [ ] **Step 3: implement.** `Issue` gains `comments: tuple[str, ...] = ()`. In `GitHubClient.issue`, after the issue is read and is not a pull request:

```python
        batch = _ISSUE_COMMENTS.validate_python(
            self._get(f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}/comments", {"per_page": _PAGE_SIZE}).json()
        )
        trusted = [
            c.body for c in batch if c.body and (c.user is None or c.user.kind != "Bot")
            and c.author_association in TRUSTED_ASSOCIATIONS
        ]
        return Issue(ref=ref, title=data.title, body=data.body or "", comments=_newest_within(trusted))
```

with

```python
_MAX_ISSUE_COMMENTS = 20
_MAX_COMMENT_CHARS = 8000


def _newest_within(bodies: list[str]) -> tuple[str, ...]:
    # Newest first until the budget runs out, then back in reading order: later comments usually settle
    # what earlier ones debated.
    kept: list[str] = []
    used = 0
    for body in reversed(bodies[-_MAX_ISSUE_COMMENTS:]):
        if used + len(body) > _MAX_COMMENT_CHARS:
            break
        kept.append(body)
        used += len(body)
    return tuple(reversed(kept))
```

Bots are left out: their comments are status, not requirements (bylaw's own summary included). In `requirements.py`, `_requirement(label, issue.title, issue.body, issue.comments)`: criteria from the body, text = body plus the comments block when there are comments.

- [ ] **Step 4:** tests pass, whole suite, ruff, mypy. Existing tests that mock `/issues/{n}` without a comments route need one; add `respx.get(.../comments).mock(return_value=httpx.Response(200, json=[]))` where they read a real issue.
- [ ] **Step 5: commit** `feat: maintainer comments on a linked issue are part of the requirement`

---

### Task 2: inferred criteria in the schema and validation

**Files:** `src/bylaw/model.py`, `src/bylaw/engine.py`, `src/bylaw/validate.py`; tests in `tests/unit/test_validate.py`, `tests/unit/test_cli.py`.

**Interfaces:**
- Produces: `CriterionResult.text: str | None = None`; `OutCriterion.text: str | None` (required, nullable, strict schema). `INFERRED_LIMIT = 5`, `INFERRED_TEXT_LIMIT = 300` in `validate.py`. A result criterion `<source>/IC-<n>` (1 <= n <= 5) is kept only when `<source>` is a requirement with no structured criteria and `text` is non-empty and at most 300 characters; otherwise it is dropped as `no such acceptance criterion` or `inferred criterion needs text`. Kept inferred keys are valid `evidence` for requirement findings.

- [ ] **Step 1: failing tests** in `tests/unit/test_validate.py`, built on its existing context helpers, one requirement `issue#7` with no criteria and one `spec.md` with `AC-1`:
  - `test_an_inferred_criterion_is_kept_for_a_requirement_without_criteria`: `CriterionResult(criterion="issue#7/IC-1", status="missing", text="Locks after five failures")` survives.
  - `test_an_inferred_criterion_is_dropped_where_criteria_are_listed`: `spec.md/IC-1` with text is dropped with `no such acceptance criterion`.
  - `test_an_inferred_criterion_without_text_is_dropped`: `issue#7/IC-1` with `text=None` is dropped with `inferred criterion needs text`.
  - `test_more_than_five_inferred_criteria_are_dropped`: `issue#7/IC-6` is dropped.
  - `test_a_requirement_finding_may_cite_an_inferred_criterion`: a `requirement` finding on an added line with `evidence="issue#7/IC-1"`, alongside that kept criterion, survives.
  - in `tests/unit/test_cli.py`, `test_the_schema_asks_for_criterion_text`: the `criteria.items` schema from `bylaw schema` lists `text` as required.
- [ ] **Step 2:** run. Expected: FAIL.
- [ ] **Step 3: implement.** Add the fields. In `validate`, before the findings loop, compute the accepted inferred keys from `result.criteria` and add them to the checker's criterion set; the criteria loop then keeps a result whose key is in the set, and for an `IC-` key also requires the text.
- [ ] **Step 4:** tests pass, whole suite, ruff, mypy.
- [ ] **Step 5: commit** `feat: reviewers may infer acceptance criteria for prose requirements`

---

### Task 3: prompt and summary

**Files:** `src/bylaw/prompt.py`, `src/bylaw/prompts/system.md`, `src/bylaw/render.py`, `src/bylaw/requirements.py` (note text); tests in `tests/unit/test_prompt.py`, `tests/unit/test_render.py`.

**Interfaces:**
- Consumes: Task 2's `CriterionResult.text` and the `IC-` labels.
- Produces: for a requirement without criteria the brief says `Criteria: none listed. Derive up to 5 testable criteria from the text and label them <source>/IC-1 to <source>/IC-5.` `system.md` explains `text` (the criterion in one sentence for inferred criteria, null otherwise). The summary lists inferred rows after the requirement, in label order, as `` `issue#7/IC-1` Locks after five failures (inferred) ``; a requirement with no criteria and no inferred ones gets one row `` `issue#7` Login | no criteria listed ``.

- [ ] **Step 1: failing tests**
  - `test_a_requirement_without_criteria_asks_for_inferred_ones` (prompt): the rendered input contains `issue#7/IC-1` guidance for a requirement with no criteria, and not for one with criteria.
  - `test_inferred_criteria_are_listed_and_marked` (render): the summary has the inferred row with `(inferred)` and its status.
  - `test_inferred_criterion_text_is_escaped` (render): text `<img src=x onerror=alert(1)> | split` appears escaped (no raw `<img`, the `|` does not split the table).
  - `test_a_requirement_with_nothing_to_assess_is_still_listed` (render): row with `no criteria listed`.
- [ ] **Step 2:** run. Expected: FAIL.
- [ ] **Step 3: implement.** Reuse `_cell` for every inferred text. The context note becomes `<source> has no structured acceptance criteria; a reviewer infers them from the text.`
- [ ] **Step 4:** tests pass, whole suite, ruff, mypy. The eval oracle test must stay green.
- [ ] **Step 5: commit** `feat: the brief asks for inferred criteria and the summary marks them`

---

### Task 4: docs and the exit check

- [ ] ADR 0011 (inferred criteria and maintainer comments): what is trusted, the caps, why criteria keys come from the body only, why inferred ones are labelled and marked. Alternatives: a separate model call to extract criteria (lost: a second paid call per requirement, and the host path would need two steps), asking users to write checklists (lost: most issues are prose).
- [ ] `docs/design.md` requirement section, `README.md` one line, `CHANGELOG.md`, ROADMAP M7 entry; remove "inferred criteria" and "issue comments as requirement text" from Known gaps and Later.
- [ ] Exit check on `bylaw-demo`, no API spend: an issue written as prose with one maintainer comment adding a requirement, a pull request that closes it, then the host path (`context --pr`, `prompt`, a result written by this session's model with `IC-` criteria, `validate`, `post --dry-run`, then `post --pr`). Expected: the comment is in the brief, the inferred rows appear marked in the summary, nothing is dropped.
