# Evaluation: claude-opus-5-5, 19 October 2026 (v0.5)

57 cases. Matching rules: docs/eval/README.md.

False alarms count findings on clean pull requests and outside the code a case adds; remarks on
planted code that are not the planted defect are listed separately, not counted.

| Category | Hits | False alarms | Misses | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| security | 11 | 1 | 0 | 92% | 100% |
| bug | 10 | 1 | 0 | 91% | 100% |
| rule | 14 | 0 | 0 | 100% | 100% |
| requirement | 0 | 0 | 0 | n/a | n/a |

- Labelled defects found at the right place, any category: 35 of 35.
- Clean pull requests with an inline comment (medium or above): 1 of 11.
- Model findings the validator dropped: 0 of 80.
- Duplicate findings: 20.
- Other remarks on planted code, not scored: 26 (17 at medium or above).
- Rule findings citing the right rule line: 11 of 11.
- Acceptance criteria judged correctly: 21 of 21.
- Scope creep found: 4 of 4, with 0 extra.
- Latency: 5.8 s median, 8.8 s p90.
- Tokens: 253,914 in, 29,051 out, over 57 reviewed cases.
- Cost: $0.04 per pull request at the given prices. Approximate: cached input is priced as plain input, and failed attempts are not counted.

## False alarms

- py-clean-contained-path: app/files.py:23 bug The check compares a resolved `target` against an unresolved `UPLOAD_DIR`. If `U
- py-clean-contained-path: app/files.py:20 security `read_upload` takes only a file name and has no notion of the requesting user. A
