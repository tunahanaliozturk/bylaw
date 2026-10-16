# ADR conformance

Roadmap: Q2 in [ROADMAP.md](../ROADMAP.md). Target: v0.4. Item ids: `ADR-n`.

Teams write decisions down and then forget them. Flag a change that contradicts an accepted ADR, citing the ADR's line.

**Done when** a change that contradicts an accepted ADR gets a `rule` finding citing it; a superseded ADR is ignored.

## Items

- [ ] **ADR-1** (M) Collect accepted ADRs from the configured globs, from the base branch. Done when: status parsing test.
- [ ] **ADR-2** (M) A `decisions` block in the brief; findings cite `docs/adr/<file>.md:<line>`. Done when: prompt and validate tests.
- [ ] **ADR-3** (S) Superseded and rejected ADRs are left out. Done when: test.
- [ ] **ADR-4** (M) Evaluation cases: a change that contradicts an ADR, and a clean change next to one. Done when: cases in the set.

## Notes

Only the title, status and decision sections go into the brief.
