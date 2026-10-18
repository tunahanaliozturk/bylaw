# Evaluation: claude-opus-5-5, 18 October 2026 (v0.3)

55 cases. Matching rules: docs/eval/README.md.

False alarms count findings on clean pull requests and outside the code a case adds; remarks on
planted code that are not the planted defect are listed separately, not counted.

| Category | Hits | False alarms | Misses | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| security | 11 | 0 | 0 | 100% | 100% |
| bug | 9 | 0 | 0 | 100% | 100% |
| rule | 14 | 0 | 0 | 100% | 100% |
| requirement | 0 | 0 | 0 | n/a | n/a |

- Labelled defects found at the right place, any category: 34 of 34.
- Clean pull requests with an inline comment (medium or above): 0 of 10.
- Model findings the validator dropped: 0 of 74.
- Duplicate findings: 17.
- Other remarks on planted code, not scored: 26 (19 at medium or above).
- Rule findings citing the right rule line: 11 of 11.
- Acceptance criteria judged correctly: 21 of 21.
- Scope creep found: 4 of 4, with 0 extra.
- Latency: 6.1 s median, 8.5 s p90.
- Tokens: 223,729 in, 28,278 out, over 55 reviewed cases.
- Cost: $0.03 per pull request at the given prices. Approximate: cached input is priced as plain input, and failed attempts are not counted.
