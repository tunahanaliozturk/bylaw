"""Review every case with one reviewer and save what would have been posted."""

import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from bylaw.engine import Reviewer, ReviewError, Usage
from bylaw.evaluation.cases import Case, build_case_context
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


class AnswerReviewer:
    """Replays the result a host model (Claude Code, Codex) wrote after `bylaw eval prepare`."""

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

    def review(self, system: str, user: str) -> ReviewResult:  # noqa: ARG002
        return ReviewResult()


def run_case(context: ReviewContext, case_id: str, reviewer: Reviewer) -> CaseRun:
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
    # Read only after a success: a reviewer reused across cases still holds the previous case's usage.
    usage: Usage | None = getattr(reviewer, "last_usage", None) if error is None else None
    return CaseRun(
        case_id=case_id,
        result=checked.result,
        dropped=checked.dropped,
        model_findings=len(result.findings),
        seconds=seconds,
        input_tokens=usage.input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        error=error,
    )


def run_all(
    root: Path, cases: Sequence[Case], make: Callable[[Case], Reviewer], out: Path, work: Path
) -> tuple[CaseRun, ...]:
    out.mkdir(parents=True, exist_ok=True)
    runs: list[CaseRun] = []
    for case in cases:
        saved = out / f"{case.id}.json"
        if saved.is_file():
            previous = CaseRun.model_validate_json(saved.read_text(encoding="utf-8"))
            # A paid review is never repeated; a failed one is retried.
            if previous.error is None:
                runs.append(previous)
                continue
        run = run_case(build_case_context(root, case, work), case.id, make(case))
        saved.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        runs.append(run)
    return tuple(runs)


def prepare(root: Path, cases: Sequence[Case], out: Path, work: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for case in cases:
        context = build_case_context(root, case, work)
        text, _ = render_input(context)
        (out / f"{case.id}.context.json").write_text(context.model_dump_json(indent=2), encoding="utf-8")
        (out / f"{case.id}.brief.txt").write_text(f"{system_prompt()}\n---\n{text}\n", encoding="utf-8")
