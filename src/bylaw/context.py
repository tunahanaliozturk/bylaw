"""Builds the ReviewContext every reviewer, built-in or host model, works from."""

from collections.abc import Sequence
from pathlib import PurePosixPath

from bylaw.config import load_config
from bylaw.editorconfig import EditorConfigResolver
from bylaw.editorconfig_checks import check
from bylaw.model import Finding, ReviewContext
from bylaw.requirements import collect_requirements
from bylaw.rules import RULE_PATHS, collect_rules
from bylaw.source import RepoSource

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


def build_context(source: RepoSource) -> ReviewContext:
    info = source.info()
    config = load_config(source.read_base(".bylaw.toml"))
    patterns = generated_patterns(source.read_base(".gitattributes"))
    all_files = source.changed_files()
    files = tuple(f for f in all_files if not is_skipped(f.path, patterns))
    notes: list[str] = []
    if skipped := len(all_files) - len(files):
        notes.append(f"Skipped {skipped} lock, vendored or generated file(s).")

    resolver = EditorConfigResolver(source.read_base)
    findings: list[Finding] = []
    for file in files:
        if file.status == "removed":
            continue
        if file.patch_omitted:
            notes.append(f"{file.path}: no patch available (binary or too large), not reviewed.")
            continue
        findings.extend(check(file, resolver.properties(file.path)))

    changed_rules = sorted(
        f.path for f in files if f.path in RULE_PATHS or PurePosixPath(f.path).name == ".editorconfig"
    )
    if changed_rules:
        notes.append(
            f"This change edits {', '.join(changed_rules)}; it is reviewed against the base branch "
            "versions (ADR 0004)."
        )

    requirements, requirement_notes = collect_requirements(
        source, info, files, config.spec_globs, config.issue_repos
    )
    return ReviewContext(
        base_sha=info.base_sha,
        head_sha=info.head_sha,
        title=info.title,
        files=files,
        rules=collect_rules(files, source.read_base, resolver.files_read),
        requirements=requirements,
        findings=tuple(findings),
        notes=(*notes, *requirement_notes),
    )
