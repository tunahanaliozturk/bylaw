"""Files bylaw 0.x wrote, read by this bylaw (V1-3). The fixtures are real output: see tests/fixtures/0.x."""

import json
from pathlib import Path

import pytest

from bylaw.cli import main
from bylaw.config import Config, load_config
from bylaw.engine import OutReview
from bylaw.evaluation.run import CaseRun
from bylaw.evidence import Evidence, build_evidence
from bylaw.github import SummaryComment
from bylaw.incremental import trusted_memory
from bylaw.model import ReviewContext, ReviewResult, Severity
from bylaw.plan import Thread, ThreadComment, added_text, group_findings, make_plan
from bylaw.publish import first_plan
from bylaw.render import read_state
from bylaw.validate import validate

FIXTURES = Path(__file__).parents[1] / "fixtures" / "0.x"


def _context(path: str) -> ReviewContext:
    return ReviewContext.model_validate_json((FIXTURES / path).read_text(encoding="utf-8"))


def _run(path: str) -> CaseRun:
    return CaseRun.model_validate_json((FIXTURES / path).read_text(encoding="utf-8"))


def test_a_context_and_a_host_result_from_0_1_still_validate_with_every_finding_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The result exactly as the host wrote it in 0.1, not as this bylaw would write it again.
    recorded = json.loads((FIXTURES / "0.1.1/cs-async-void.run.json").read_text(encoding="utf-8"))["result"]
    answer = tmp_path / "result.json"
    answer.write_text(json.dumps(recorded), encoding="utf-8")
    result = ReviewResult.model_validate(recorded)

    code = main(
        ["validate", "--context", str(FIXTURES / "0.1.1/cs-async-void.context.json"), "--result", str(answer)]
    )

    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert printed["dropped"] == []
    assert ReviewResult.model_validate(printed["result"]).findings == result.findings


def test_a_summary_from_0_2_keeps_the_threads_it_resolved_and_its_review_memory() -> None:
    body = (FIXTURES / "0.2.0/summary.md").read_text(encoding="utf-8")

    state = read_state(body)
    memory = trusted_memory(SummaryComment(1, body, bot=True))

    assert state.auto_resolved == frozenset({"PRRT_fixed"})
    assert memory is not None
    assert (memory.tokens, len(memory.findings), sorted(memory.files)) == (
        48_210,
        1,
        ["OrderService.cs", "OrdersController.cs"],
    )


def test_threads_from_0_2_pair_with_their_findings_and_one_it_resolved_reopens_when_the_finding_returns() -> (
    None
):
    context = _context("0.2.0/cs-async-void.context.json")
    findings = _run("0.1.1/cs-async-void.run.json").result.findings
    saved = json.loads((FIXTURES / "0.2.0/threads.json").read_text(encoding="utf-8"))
    threads = [
        Thread(
            t["id"],
            t["id"] == "PRRT_fixed",
            (ThreadComment(t["body"], True),),
            t["line"],
            t["line"],
            t["path"],
        )
        for t in saved
    ]
    state = read_state((FIXTURES / "0.2.0/summary.md").read_text(encoding="utf-8"))

    plan = make_plan(group_findings(findings, added_text(context)), threads, state, Severity.MEDIUM, 15)

    # Nothing is posted twice: the fingerprints 0.2.0 wrote are the ones this bylaw computes.
    assert plan.inline == ()
    assert plan.unresolve == ("PRRT_fixed",)
    assert len(plan.open_threads) == 2


def test_evidence_written_by_0_6_reads_back_field_for_field() -> None:
    raw = (FIXTURES / "0.6.0/evidence.json").read_text(encoding="utf-8")

    evidence = Evidence.model_validate_json(raw)

    assert evidence.schema_version == 1
    assert json.loads(evidence.model_dump_json()) == json.loads(raw)


def test_a_0_6_context_and_result_still_build_the_evidence_0_6_wrote() -> None:
    context = _context("0.6.0/py-iso-logs-password.context.json")
    result = _run("0.6.0/py-iso-logs-password.run.json").result
    recorded = Evidence.model_validate_json((FIXTURES / "0.6.0/evidence.json").read_text(encoding="utf-8"))
    checked = validate(context, result.model_copy(update={"findings": (*context.findings, *result.findings)}))
    settings = Config(severity_threshold=context.severity_threshold, max_comments=context.max_comments)

    built = build_evidence(context, checked.result, first_plan(context, checked.result, settings))

    stamped = {"generated_at", "repository", "pull_request", "bylaw_version"}
    assert built.model_dump(exclude=stamped) == recorded.model_dump(exclude=stamped)


def test_a_0_6_configuration_with_every_key_and_no_version_still_loads() -> None:
    config = load_config((FIXTURES / "0.6.0/bylaw.toml").read_text(encoding="utf-8"))

    assert config.profiles == ("iso27001",)
    assert config.jira is not None
    assert config.jira.criteria_field == "customfield_10042"
    assert config.app.model_review == "all"


def test_files_from_0_x_have_no_schema_version_and_read_as_version_1() -> None:
    assert _context("0.1.1/cs-async-void.context.json").schema_version == 1
    assert _run("0.1.1/cs-async-void.run.json").result.schema_version == 1


def test_the_context_and_result_bylaw_writes_carry_their_schema_version() -> None:
    written = json.loads(_context("0.2.0/cs-async-void.context.json").model_dump_json())

    assert written["schema_version"] == 1
    assert json.loads(ReviewResult().model_dump_json())["schema_version"] == 1


def test_the_model_is_never_asked_for_a_schema_version() -> None:
    # The model fills OutReview; bylaw adds the version when it writes a file (ADR 0023).
    assert "schema_version" not in json.dumps(OutReview.model_json_schema())
    assert OutReview(findings=[], criteria=[], scope_creep=[]).to_result().schema_version == 1


@pytest.mark.parametrize("option", ["--context", "--result"])
def test_a_file_with_an_unknown_schema_version_fails_and_names_the_versions_bylaw_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], option: str
) -> None:
    context = json.loads((FIXTURES / "0.1.1/cs-async-void.context.json").read_text(encoding="utf-8"))
    files = {"--context": context, "--result": {"findings": []}}
    files[option] = {**files[option], "schema_version": 2}
    paths = {name: tmp_path / f"{name[2:]}.json" for name in files}
    for name, data in files.items():
        paths[name].write_text(json.dumps(data), encoding="utf-8")

    code = main(["validate", "--context", str(paths["--context"]), "--result", str(paths["--result"])])

    assert code == 2
    assert "schema_version 2" in capsys.readouterr().err
