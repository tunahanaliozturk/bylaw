# Evaluation: claude-opus-5-5, 18 October 2026 (v0.4)

57 cases. Matching rules: docs/eval/README.md.

False alarms count findings on clean pull requests and outside the code a case adds; remarks on
planted code that are not the planted defect are listed separately, not counted.

| Category | Hits | False alarms | Misses | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| security | 11 | 0 | 0 | 100% | 100% |
| bug | 10 | 1 | 0 | 91% | 100% |
| rule | 14 | 0 | 0 | 100% | 100% |
| requirement | 0 | 0 | 0 | n/a | n/a |

- Labelled defects found at the right place, any category: 35 of 35.
- Clean pull requests with an inline comment (medium or above): 0 of 11.
- Model findings the validator dropped: 0 of 75.
- Duplicate findings: 17.
- Other remarks on planted code, not scored: 25 (15 at medium or above).
- Rule findings citing the right rule line: 11 of 11.
- Acceptance criteria judged correctly: 21 of 21.
- Scope creep found: 4 of 4, with 0 extra.
- Latency: 6.1 s median, 9.1 s p90.
- Tokens: 253,832 in, 28,951 out, over 57 reviewed cases.
- Cost: $0.03 per pull request at the given prices. Approximate: cached input is priced as plain input, and failed attempts are not counted.

## False alarms

- py-clean-contained-path: app/files.py:23 bug `target` is resolved, but it is compared against an unresolved `UPLOAD_DIR`. If 
