# Evaluation: bylaw checks only, no model, 2026-10-19

60 cases. Matching rules: docs/eval/README.md.

False alarms count findings on clean pull requests and outside the code a case adds; remarks on
planted code that are not the planted defect are listed separately, not counted.

| Category | Hits | False alarms | Misses | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| security | 0 | 0 | 12 | n/a | 0% |
| bug | 0 | 0 | 10 | n/a | 0% |
| rule | 3 | 0 | 12 | 100% | 20% |
| requirement | 0 | 0 | 0 | n/a | n/a |

- Labelled defects found at the right place, any category: 3 of 37.
- Clean pull requests with an inline comment (medium or above): 0 of 12.
- Model findings the validator dropped: 0 of 0.
- Duplicate findings: 0.
- Other remarks on planted code, not scored: 0 (0 at medium or above).
- Rule findings citing the right rule line: 0 of 0.
- Profile findings tagged with a labelled control: 0 of 0.
- Acceptance criteria judged correctly: 0 of 21.
- Scope creep found: 0 of 4, with 0 extra.

## Misses

- cs-async-void: async void: exceptions crash the process and the call is not awaited
- cs-blocking-result: blocks on a task with .Result
- cs-null-after-firstordefault: FirstOrDefault result dereferenced without a null check
- cs-sqli-fromsqlraw: FromSqlRaw with the customer interpolated into the SQL
- go-ignored-unmarshal: Unmarshal error ignored: bad input reports success
- go-nil-map: writes to a nil map, which panics
- go-panic-handler: panics in a handler on a bad id
- go-sqli-sprintf: query built with Sprintf from the name
- py-command-injection: client-supplied name interpolated into a shell command
- py-hardcoded-secret: API token committed as a string literal
- py-iso-logs-password: writes the password of a failed sign-in to the log
- py-iso-md5-password: stores passwords as a fast MD5 hash instead of scrypt
- py-ledger-adr-own-connection: the report opens its own SQLite connection and runs SQL, where the accepted ADR 0002 keeps all of that in ledger/store.py
- py-logs-email: logs the user's email address
- py-mono-api-raises: an API handler raises for a missing order, where the package's AGENTS.md asks for an error Result
- py-mono-api-sqli-ruff: SQL built with an f-string from the status argument, which ruff's S608 flags
- py-mono-worker-default-ruff: mutable default list, shared between calls, which ruff's B006 flags
- py-mono-worker-error-value: a job returns an error value, which the queue takes as success; the worker's AGENTS.md asks it to raise
- py-mutable-default: mutable default list is shared between calls
- py-naive-aware-compare: naive now() compared with the aware expiry raises TypeError
- py-new-dependency: third-party dependency added without an ADR
- py-page-off-by-one: a page returns size + 1 users
- py-path-traversal: client-supplied file name joined to the upload directory without a containment check
- py-pickle-cookie: unpickles a client-controlled cookie
- py-print: print instead of logging
- py-sqli-fstring: SQL built with an f-string from the email argument
- py-swallowed-commit: every exception inside the block is swallowed, so failed writes look successful
- py-weak-reset-token: reset token from the non-cryptographic random module
- ts-console-log: console.log instead of logger
- ts-float-money: money in floating point
- ts-missing-await: responds 201 before the order is saved; a failure is lost
- ts-missing-ownership: cancels any user's order: no ownership check
- ts-reduce-no-initial: reduce with no initial value throws on an empty cart
- ts-xss-search: query text written into HTML unescaped
