# Evaluation: claude-opus-5-5, 19 October 2026 (v0.6)

60 cases. Matching rules: docs/eval/README.md.

False alarms count findings on clean pull requests and outside the code a case adds; remarks on
planted code that are not the planted defect are listed separately, not counted.

| Category | Hits | False alarms | Misses | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| security | 13 | 1 | 0 | 93% | 100% |
| bug | 10 | 1 | 0 | 91% | 100% |
| rule | 14 | 0 | 0 | 100% | 100% |
| requirement | 0 | 0 | 0 | n/a | n/a |

- Labelled defects found at the right place, any category: 37 of 37.
- Clean pull requests with an inline comment (medium or above): 1 of 12.
- Model findings the validator dropped: 0 of 87.
- Duplicate findings: 24.
- Other remarks on planted code, not scored: 27 (18 at medium or above).
- Rule findings citing the right rule line: 11 of 11.
- Profile findings tagged with a labelled control: 2 of 2.
- Acceptance criteria judged correctly: 21 of 21.
- Scope creep found: 4 of 4, with 0 extra.
- Latency: 6.0 s median, 9.5 s p90.
- Tokens: 285,211 in, 30,316 out, over 60 reviewed cases.
- Cost: $0.04 per pull request at the given prices. Approximate: cached input is priced as plain input, and failed attempts are not counted.

## False alarms

- py-clean-contained-path: app/files.py:23 bug The containment check compares a resolved `target` with an unresolved `UPLOAD_DI
- py-iso-clean-sign-in-log: app/accounts.py:42 security Only wrong-password failures are logged. The earlier `return None` for an email 
