"""Compliance profiles (ADR 0021): control ids, bylaw's own guidance for reviewers, and severity rules.

A profile ships inside bylaw, so a repository cannot redefine a control to pass its own review.
"""

import tomllib
from functools import cache
from importlib.resources import files
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bylaw.model import Category, Finding, Severity


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Control(_Frozen):
    id: str = Field(pattern=r"^[0-9]+(\.[0-9]+)*$")
    # bylaw's own short name and guidance, never the standard's text.
    title: str
    guidance: str


class SeverityRule(_Frozen):
    """A finding that carries all of `controls`, and is of `category` when set, is at least `minimum`."""

    controls: tuple[str, ...] = Field(min_length=1)
    category: Category | None = None
    minimum: Severity
    why: str


class Profile(_Frozen):
    name: str
    standard: str
    controls: tuple[Control, ...] = Field(min_length=1)
    severity_rules: tuple[SeverityRule, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = [control.id for control in self.controls]
        if twice := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"control ids listed twice: {', '.join(twice)}")
        if unknown := sorted({c for rule in self.severity_rules for c in rule.controls} - set(ids)):
            raise ValueError(f"severity rules name undefined controls: {', '.join(unknown)}")
        return self


_DIRECTORY = files("bylaw").joinpath("profiles")


def available() -> tuple[str, ...]:
    names = (p.name.removesuffix(".toml") for p in _DIRECTORY.iterdir() if p.name.endswith(".toml"))
    return tuple(sorted(names))


@cache
def load_profile(name: str) -> Profile:
    if name not in available():
        raise ValueError(f"unknown compliance profile {name!r}; bylaw has {', '.join(available())}")
    text = _DIRECTORY.joinpath(f"{name}.toml").read_text(encoding="utf-8")
    return Profile.model_validate({**tomllib.loads(text), "name": name})


_RANK = {severity: rank for rank, severity in enumerate(Severity)}


def with_severity_rules(profiles: tuple[str, ...], finding: Finding) -> Finding:
    """The finding raised to the minimum of every rule it meets. Applied by bylaw after validation, so the
    same tags always give the same severity; a rule never lowers one (ADR 0021)."""
    severity = finding.severity
    for name in profiles:
        for rule in load_profile(name).severity_rules:
            meets = set(rule.controls) <= set(finding.controls) and rule.category in (None, finding.category)
            if meets and _RANK[rule.minimum] < _RANK[severity]:
                severity = rule.minimum
    return finding if severity == finding.severity else finding.model_copy(update={"severity": severity})
