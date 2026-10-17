# Evaluation: claude-opus-5-5, 18 October 2026 (v0.2)

50 cases. Matching rules: docs/eval/README.md.

False alarms count findings on clean pull requests and outside the code a case adds; remarks on
planted code that are not the planted defect are listed separately, not counted.

| Category | Hits | False alarms | Misses | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| security | 10 | 0 | 0 | 100% | 100% |
| bug | 9 | 2 | 0 | 82% | 100% |
| rule | 11 | 0 | 0 | 100% | 100% |
| requirement | 0 | 0 | 0 | n/a | n/a |

- Labelled defects found at the right place, any category: 30 of 30.
- Clean pull requests with an inline comment (medium or above): 2 of 9.
- Model findings the validator dropped: 0 of 71.
- Duplicate findings: 18.
- Other remarks on planted code, not scored: 24 (17 at medium or above).
- Rule findings citing the right rule line: 8 of 8.
- Acceptance criteria judged correctly: 21 of 21.
- Scope creep found: 4 of 4, with 0 extra.
- Latency: 6.5 s median, 10.1 s p90.
- Tokens: 195,079 in, 27,266 out, over 50 reviewed cases.
- Cost: $0.03 per pull request at the given prices. Approximate: cached input is priced as plain input, and failed attempts are not counted.

## False alarms

- cs-clean-service: OrderService.cs:29 bug `CancelAsync` permanently deletes the order row instead of marking it cancelled.
- py-clean-contained-path: app/files.py:23 bug The resolved target is compared with an unresolved `UPLOAD_DIR`. If `UPLOAD_DIR`
