"""Builds the ReviewContext every reviewer, built-in or host model, works from."""

import os
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from bylaw.config import Config, load_config
from bylaw.decisions import collect_decisions, is_adr
from bylaw.editorconfig import EditorConfigResolver
from bylaw.editorconfig_checks import check
from bylaw.model import ChangedFile, Finding, ReviewContext
from bylaw.requirements import collect_requirements, linked_paths
from bylaw.rules import collect_rules, is_rule_file
from bylaw.source import RepoSource
from bylaw.trackers import read_work_items

LOCKFILES = frozenset(
    {
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "Cargo.lock",
        "go.sum",
        "composer.lock",
        "Gemfile.lock",
        "packages.lock.json",
    }
)
VENDOR_DIRS = frozenset({"vendor", "node_modules", "third_party"})
_GENERATED_ATTRIBUTES = frozenset(
    {"linguist-generated", "linguist-generated=true", "linguist-vendored", "linguist-vendored=true"}
)


def generated_patterns(gitattributes: str | None) -> tuple[str, ...]:
    if gitattributes is None:
        return ()
    patterns: list[str] = []
    for line in gitattributes.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0].startswith("#"):  # noqa: PLR2004 - a pattern and at least one attribute
            continue
        if _GENERATED_ATTRIBUTES.intersection(parts[1:]):
            pattern = parts[0]
            patterns.append(pattern.removeprefix("/") if "/" in pattern else f"**/{pattern}")
    return tuple(patterns)


def is_skipped(path: str, patterns: Sequence[str]) -> bool:
    pure = PurePosixPath(path)
    return (
        pure.name in LOCKFILES
        or not VENDOR_DIRS.isdisjoint(pure.parts[:-1])
        or any(pure.full_match(pattern) for pattern in patterns)
    )


_LISTED = 10


def _no_patch_note(file: ChangedFile) -> str | None:
    if file.changes is None:
        return f"{file.path}: binary file, not reviewed."
    if file.changes > 0:
        return f"{file.path}: diff too large for the host to show, not reviewed."
    if file.status == "renamed":
        return None  # moved without edits: nothing to review, nothing worth a note
    return f"{file.path}: binary, empty or permission-only change, nothing to review."


def build_context(
    source: RepoSource,
    env: Mapping[str, str] | None = None,
    config: Config | None = None,
    *,
    operator_sites: bool = False,
) -> ReviewContext:
    """`env` holds the tracker tokens; the process environment when not given (ADR 0014). `config` is the
    base branch's `.bylaw.toml`, read here when not given. `operator_sites`: the tokens serve a whole
    GitHub App installation, so `env` also says where they may go (ADR 0017)."""
    info = source.info()
    if config is None:
        config = load_config(source.read_base(".bylaw.toml"))
    patterns = generated_patterns(source.read_base(".gitattributes"))
    all_files = source.changed_files()
    files = tuple(f for f in all_files if not is_skipped(f.path, patterns))
    notes: list[str] = []
    if info.file_count is not None and info.file_count > len(all_files):
        notes.append(
            f"GitHub lists at most 3000 files: {len(all_files)} of {info.file_count} changed files were read."
        )
    if skipped := [f.path for f in all_files if f not in files]:
        shown = ", ".join(skipped[:_LISTED])
        more = f", and {len(skipped) - _LISTED} more" if len(skipped) > _LISTED else ""
        notes.append(f"Skipped {len(skipped)} lock, vendored or generated file(s): {shown}{more}.")

    resolver = EditorConfigResolver(source.read_base)
    findings: list[Finding] = []
    for file in files:
        if file.status == "removed":
            continue
        if file.patch_omitted:
            if note := _no_patch_note(file):
                notes.append(note)
            continue
        findings.extend(check(file, resolver.properties(file.path)))
    notes.extend(resolver.problems)

    added_adrs = sorted(f.path for f in files if f.status == "added" and is_adr(f.path, config.adr_globs))
    changed_rules = sorted(
        f.path
        for f in files
        if is_rule_file(f.path) or (is_adr(f.path, config.adr_globs) and f.path not in added_adrs)
    )
    if added_adrs:
        notes.append(
            f"This change adds {', '.join(added_adrs)}. An ADR is a decision once it is on the base branch, "
            "so the change is not checked against it yet."
        )
    if changed_rules:
        notes.append(
            f"This change edits {', '.join(changed_rules)}; it is reviewed against the base branch "
            "versions (ADR 0004)."
        )

    rules, rule_notes = collect_rules(files, source, resolver.files_read)
    notes.extend(rule_notes)
    requirements, requirement_notes = collect_requirements(
        source, info, files, config.spec_globs, config.issue_repos, adr_globs=config.adr_globs
    )
    decisions, decision_notes = collect_decisions(source, config.adr_globs, [f.path for f in files])
    notes.extend(decision_notes)
    decided = {decision.path for decision in decisions}
    for path in linked_paths(info.body, source.repo):
        if is_adr(path, config.adr_globs) and path not in decided and path not in added_adrs:
            notes.append(
                f"{path} is linked as an ADR, but it is not an accepted decision on the base branch for this "
                "change, or it was left out as noted, so the change is not checked against it."
            )
    # Work items are referenced from the same text as issues, and from the title, where keys often sit.
    work_items, work_item_notes = read_work_items(
        [info.title, info.body, *info.commit_messages],
        config,
        os.environ if env is None else env,
        author_trusted=info.author_trusted is not False,
        operator_sites=operator_sites,
    )
    return ReviewContext(
        base_sha=info.base_sha,
        head_sha=info.head_sha,
        title=info.title,
        files=files,
        rules=rules,
        decisions=decisions,
        requirements=(*requirements, *work_items),
        findings=tuple(findings),
        notes=(*notes, *requirement_notes, *work_item_notes),
        severity_threshold=config.severity_threshold,
        max_comments=config.max_comments,
        input_tokens=config.input_token_budget,
    )
