# Evaluation: Claude Code as host (Opus), 2026-10-16

50 cases. Matching rules: docs/eval/README.md.

False alarms count findings on clean pull requests and outside the code a case adds; remarks on
planted code that are not the planted defect are listed separately, not counted.

| Category | Hits | False alarms | Misses | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| security | 10 | 0 | 0 | 100% | 100% |
| bug | 9 | 0 | 0 | 100% | 100% |
| rule | 11 | 0 | 0 | 100% | 100% |
| requirement | 0 | 0 | 0 | n/a | n/a |

- Labelled defects found at the right place, any category: 30 of 30.
- Clean pull requests with an inline comment (medium or above): 0 of 9.
- Model findings the validator dropped: 0 of 53.
- Duplicate findings: 9.
- Other remarks on planted code, not scored: 17 (11 at medium or above).
- Rule findings citing the right rule line: 8 of 8.
- Acceptance criteria judged correctly: 21 of 21.
- Scope creep found: 4 of 4, with 0 extra.
