# Evaluation: claude-opus-5-5, effort high, 2026-10-16

50 cases. Matching rules: docs/eval/README.md.

False alarms count findings on clean pull requests and outside the code a case adds; remarks on
planted code that are not the planted defect are listed separately, not counted.

| Category | Hits | False alarms | Misses | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| security | 10 | 0 | 0 | 100% | 100% |
| bug | 9 | 1 | 0 | 90% | 100% |
| rule | 11 | 0 | 0 | 100% | 100% |
| requirement | 0 | 0 | 0 | n/a | n/a |

- Labelled defects found at the right place, any category: 30 of 30.
- Clean pull requests with an inline comment (medium or above): 1 of 9.
- Model findings the validator dropped: 1 of 74.
- Duplicate findings: 16.
- Other remarks on planted code, not scored: 29 (20 at medium or above).
- Rule findings citing the right rule line: 8 of 8.
- Acceptance criteria judged correctly: 21 of 21.
- Scope creep found: 4 of 4, with 0 extra.
- Latency: 6.5 s median, 10.1 s p90.
- Tokens: 194,927 in, 25,840 out, over 50 reviewed cases.
- Cost: $0.03 per pull request at the given prices. Approximate: cached input is priced as plain input, and failed attempts are not counted.

## False alarms

- py-clean-contained-path: app/files.py:23 bug The path is resolved but `UPLOAD_DIR` is not. If `UPLOAD_DIR` is relative or pas
