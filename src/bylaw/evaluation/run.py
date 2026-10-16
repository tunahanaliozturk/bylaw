"""Review every case with one reviewer and save what would have been posted."""

import json
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from bylaw.engine import Reviewer, ReviewError, Usage
from bylaw.evaluation.cases import Case, build_case_context, case_digest
from bylaw.model import ReviewContext, ReviewResult
from bylaw.prompt import render_input, system_prompt
from bylaw.validate import validate


class CaseRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    result: ReviewResult
    dropped: tuple[str, ...]
    model_findings: int
    seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    # Who reviewed and what they saw: a rerun never mixes reviewers or reuses a review of an older case.
    reviewer: str = ""
    case_digest: str = ""
    dropped_findings: int = 0


class AnswerReviewer:
    """Replays the result a host model (Claude Code, Codex) wrote after `bylaw eval prepare`."""

    timed = False  # reading a file says nothing about how long the host took

    def __init__(self, path: Path) -> None:
        self._path = path

    def review(self, system: str, user: str) -> ReviewResult:  # noqa: ARG002 - the host already read the brief
        if not self._path.is_file():
            raise ReviewError(f"no answer at {self._path.name}")
        raw = self._path.read_bytes()
        try:
            return ReviewResult.model_validate_json(raw.decode(json.detect_encoding(raw)))
        except ValidationError as error:
            raise ReviewError(
                f"{self._path.name} is not a valid review ({error.error_count()} errors)"
            ) from error


class NoModel:
    """bylaw's own checks only: what a repository without a model key gets."""

    timed = False

    def review(self, system: str, user: str) -> ReviewResult:  # noqa: ARG002
        return ReviewResult()


def run_case(
    context: ReviewContext, case_id: str, reviewer: Reviewer, *, identity: str = "", digest: str = ""
) -> CaseRun:
    text, _ = render_input(context)
    error: str | None = None
    start = time.perf_counter()
    try:
        result = reviewer.review(system_prompt(), text)
    except ReviewError as failure:
        result, error = ReviewResult(), str(failure)
    seconds = time.perf_counter() - start
    merged = result.model_copy(update={"findings": (*context.findings, *result.findings)})
    checked = validate(context, merged)
    # Engines reset this at the start of each review, so it is this case's usage, billed failures included.
    usage: Usage | None = getattr(reviewer, "last_usage", None)
    return CaseRun(
        case_id=case_id,
        result=checked.result,
        dropped=checked.dropped,
        model_findings=len(result.findings),
        seconds=seconds if getattr(reviewer, "timed", True) else None,
        input_tokens=usage.input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        error=error,
        reviewer=identity,
        case_digest=digest,
        dropped_findings=len(merged.findings) - len(checked.result.findings),
    )


def run_all(  # noqa: PLR0913 - the spending limit is an optional keyword
    root: Path,
    cases: Sequence[Case],
    make: Callable[[Case], Reviewer],
    out: Path,
    reviewer: str,
    *,
    stop: Callable[[Sequence[CaseRun]], bool] | None = None,
) -> tuple[CaseRun, ...]:
    out.mkdir(parents=True, exist_ok=True)
    runs: list[CaseRun] = []
    with tempfile.TemporaryDirectory() as work:
        for case in cases:
            saved = out / f"{case.id}.json"
            digest = case_digest(root, case)
            if saved.is_file():
                previous = CaseRun.model_validate_json(saved.read_text(encoding="utf-8"))
                if previous.reviewer != reviewer:
                    raise ValueError(
                        f"{out} holds runs by {previous.reviewer}; use another --out for {reviewer}"
                    )
                # A paid review is never repeated; a failed one, or one of a case that changed since, is.
                if previous.error is None and previous.case_digest == digest:
                    runs.append(previous)
                    continue
            if stop is not None and stop(runs):
                # A spending limit: no new paid review starts once it is reached; saved ones still count.
                break
            context = build_case_context(root, case, Path(work))
            run = run_case(context, case.id, make(case), identity=reviewer, digest=digest)
            # Write then rename: a run killed mid-write must not leave a file that breaks every rerun.
            partial = saved.with_suffix(".part")
            partial.write_text(run.model_dump_json(indent=2), encoding="utf-8")
            partial.replace(saved)
            runs.append(run)
    return tuple(runs)


def prepare(root: Path, cases: Sequence[Case], out: Path, work: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for case in cases:
        context = build_case_context(root, case, work)
        text, _ = render_input(context)
        (out / f"{case.id}.context.json").write_text(context.model_dump_json(indent=2), encoding="utf-8")
        (out / f"{case.id}.brief.txt").write_text(f"{system_prompt()}\n---\n{text}\n", encoding="utf-8")
