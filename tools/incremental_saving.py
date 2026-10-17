"""Measure what incremental review saves on a second push, using the evaluation cases (INC-7).

usage: uv run python tools/incremental_saving.py [--out eval/results/<date>-incremental-saving.md]

For every case that changes at least two files: review the change once, then add one comment line to one
of its files, as a second push would, and review again. Both reviews use a reviewer that records what it
was sent instead of calling a model, so this costs nothing. Tokens are estimated from characters the
same way bylaw sizes its input (`CHARS_PER_TOKEN`), system prompt included.
"""

import argparse
import shutil
import tempfile
from pathlib import Path

from bylaw.engine import Usage
from bylaw.evaluation.cases import build_case_context, load_cases
from bylaw.incremental import run_model_review
from bylaw.model import ReviewResult
from bylaw.prompt import CHARS_PER_TOKEN

ROOT = Path(__file__).resolve().parents[1]
_COMMENT = {
    ".py": "# second push\n",
    ".ts": "// second push\n",
    ".go": "// second push\n",
    ".cs": "// second push\n",
}


class Recorder:
    """Records the brief and reports its estimated size as usage, so memory counts tokens as a model would."""

    def __init__(self) -> None:
        self.tokens: list[int] = []
        self.last_usage: Usage | None = None

    def review(self, system: str, user: str) -> ReviewResult:
        estimate = (len(system) + len(user)) // CHARS_PER_TOKEN
        self.tokens.append(estimate)
        self.last_usage = Usage(input_tokens=estimate, output_tokens=0)
        return ReviewResult()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write the Markdown report here instead of printing it")
    args = parser.parse_args()
    rows: list[tuple[str, int, int, int]] = []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "eval"
        shutil.copytree(ROOT / "eval" / "projects", root / "projects")
        shutil.copytree(ROOT / "eval" / "cases", root / "cases")
        for case in load_cases(root):
            head = root / "cases" / case.id / "head"
            files = sorted((p for p in head.rglob("*") if p.is_file() and p.suffix in _COMMENT), key=_size)
            if len(files) < 2:  # noqa: PLR2004 - a second push needs a file to leave alone
                continue
            recorder = Recorder()
            first = build_case_context(root, case, Path(temp) / "first")
            memory = run_model_review(first, lambda r=recorder: r, None, incremental=True, budget=None).memory
            edited = files[0]
            edited.write_text(edited.read_text(encoding="utf-8") + _COMMENT[edited.suffix], encoding="utf-8")
            second = build_case_context(root, case, Path(temp) / "second")
            full = Recorder()
            run_model_review(second, lambda r=full: r, None, incremental=True, budget=None)
            run_model_review(second, lambda r=recorder: r, memory, incremental=True, budget=None)
            rows.append((case.id, len(second.files), full.tokens[0], recorder.tokens[-1]))
    report = _report(rows)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        print(report, end="")


def _size(path: Path) -> int:
    return path.stat().st_size


def _report(rows: list[tuple[str, int, int, int]]) -> str:
    lines = [
        "# Incremental review: input on a second push",
        "",
        "Each case is reviewed once; then one comment line is added to its smallest changed file and it is "
        "reviewed again, in full and incrementally. Input tokens are estimated from characters "
        f"({CHARS_PER_TOKEN} per token, system prompt included); no model was called. "
        "Script: `tools/incremental_saving.py`.",
        "",
        "| Case | Changed files | Full review | Incremental | Saved |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case_id, count, full, incremental in rows:
        lines.append(f"| {case_id} | {count} | {full:,} | {incremental:,} | {1 - incremental / full:.0%} |")
    total_full = sum(r[2] for r in rows)
    total_incremental = sum(r[3] for r in rows)
    lines += [
        f"| **All {len(rows)} cases** | | **{total_full:,}** | **{total_incremental:,}** | "
        f"**{1 - total_incremental / total_full:.0%}** |",
        "",
        "The system prompt is sent on every run, so a second push always costs at least that much. The "
        "evaluation cases are small; on a long pull request the unchanged files are a larger share and the "
        "saving grows with them.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
