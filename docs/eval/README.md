# Evaluation

The README's quality numbers come from here: 60 labelled pull requests, a runner that reviews them with any model or host, and a scorer. Results are per model and date, not per release (ADR 0001), because the same bylaw gives different results with different models.

## The set

Each case is a small base project in `eval/projects/` plus the files one pull request changes, in `eval/cases/<id>/head/`, and a `case.toml` with the labels. bylaw builds a throwaway git repository per case (base commit, then the change) and collects the context exactly as `bylaw context --base` does, so the reviewer sees what it would see on a real pull request.

There are seven base projects, so the set is not only Python: `py-users` (Python), `ts-shop` (TypeScript), `go-api` (Go), `cs-orders` (C#), `py-mono`, `py-ledger` and `py-payments`. Each of the first four has an `.editorconfig` and a `CONTRIBUTING.md` whose rules the cases break.

`py-mono` is a monorepo with two packages whose rules conflict (ADR 0013): `packages/api/AGENTS.md` says handlers return errors and never raise, `packages/worker/AGENTS.md` says jobs raise and never return an error. Each package has its own Ruff configuration, the API's selecting `S` and the worker's `B`. Its five cases check that a change is held to the nearest package's rules and not the other's, including a clean change that raises in the worker, and two of them can only cite a linter rule id (`ruff:S608`, `ruff:B006`), because no prose rule covers the defect.

`py-ledger` has three ADRs (ADR 0016): a superseded one that kept the ledger in JSON files, an accepted one that lets only `ledger/store.py` open connections and run SQL, and a proposed one that would make every database function `async`. One case opens a connection in a report and can only be caught by citing the accepted decision's line. The other adds the same report through a new store function, which is clean only if the superseded and the proposed ADR are left out, as they should be.

`py-payments` turns the `iso27001` compliance profile on in its `.bylaw.toml` (ADR 0021), the only project that does, so the rest of the set is reviewed as before. One change writes the password of a failed sign-in to the log, another stores passwords as salted MD5 instead of scrypt, and a clean one logs failed sign-ins by account id with a test. The labels of the first two name the controls a right answer tags: 8.15 and 8.11 for the log, 8.24 for the hash.

| Kind | Cases | What is planted |
| --- | --- | --- |
| security | 12 | SQL injection (four languages), path traversal, hardcoded secret, shell injection, unpickling a cookie, weak reset token, reflected XSS, missing ownership check, and under the ISO/IEC 27001 profile a password in a log and passwords hashed with MD5 |
| bug | 10 | mutable default, off-by-one page, swallowed exception, naive and aware datetimes, missing await, `reduce` without a start value, nil map write, ignored decode error, `async void`, null dereference |
| rule | 15 | three `.editorconfig` breaks bylaw finds itself, seven `CONTRIBUTING.md` rules, two package `AGENTS.md` rules, two Ruff rule ids and one accepted ADR |
| requirement | 7 | a spec with acceptance criteria that the change meets, half meets or misses |
| scope | 4 | a change that does what its spec asks and something it does not |
| clean | 12 | changes with nothing to report, some of them built to look like the planted ones, one next to a superseded and a proposed ADR it would break, one that logs a failed sign-in safely under the profile |

Planted secrets are fake and shaped like no provider's key. Files under `eval/` keep their exact bytes: `.gitattributes` marks them `-text`, and `eval/.editorconfig` stops editors applying this repository's rules to them, because a tab, a trailing space or a missing final newline can be the label.

## Labels

A `case.toml` names the project, the kind, the pull request title and commit message, and:

- `[[findings]]`: each planted defect, with the lines it covers, the categories that count as right (an SQL injection is `security`, and also `rule` where `CONTRIBUTING.md` forbids string-built SQL), a note, and for rule findings the rule line or linter rule id a reviewer should cite. `deterministic = true` marks the ones bylaw's own `.editorconfig` checks find. In a project with a compliance profile on, `controls` lists the control ids a right answer may tag.
- `[[allowed]]`: spans where a finding is neither required nor a false alarm. Every non-clean case allows remarks on the code it adds, so a fair second comment on new code does not count against the reviewer. Clean cases allow nothing.
- `[criteria]`: for each acceptance criterion, the statuses that count as right. Two statuses are accepted where reasonable reviewers differ, for example `partial` or `missing` for a threshold implemented with `>` where the spec says "100 or more".
- `[[scope_creep]]`: the line where unrequested behaviour starts.

`tests/integration/test_eval_set.py` keeps the labels honest: a reviewer that answers with exactly the labels must score perfectly, so a label on a line the change does not add, a rule line that does not exist, or a criterion key that bylaw does not collect fails the build.

## Matching

- A finding matches a label when the file is the same, its lines come within 2 lines of the label's lines, and its category is one the label accepts. Each label matches once.
- A finding near an already matched label, in any category, is a duplicate: counted, not a false alarm.
- A finding near an unmatched label but in a category the label does not accept leaves the label a miss, and the label counts as located: the reviewer found the defect and named it wrongly. It is not a false alarm.
- A finding inside an `allowed` span is reported as another remark on planted code, not scored.
- Any other finding is a false alarm in its category. So false alarms, and precision, come from clean pull requests and from code a case does not add; the report gives the number of other remarks next to them.
- A label nothing matched is a miss in its first category. Each label is located at most once, whatever order the findings come in.
- A clean case has an inline comment when a finding of medium severity or above remains after the rules above.
- A label may list other places where the same defect can fairly be anchored (`also`), such as the call of a broken method; a finding at any of them counts.
- A rule finding that hits a label is also checked for its citation: the report gives how many cited the label's rule line or rule id.
- A finding that hits a label with `controls` is also checked for its tags: the report gives how many named at least one of the label's controls.
- A criterion is right when the run's status is one of the accepted statuses.
- Scope creep matches on file and line within 2 lines.
- A case with no run is listed under errors and scored as if nothing was found. A case whose review failed is listed under errors and scored with what bylaw's own checks found.

Findings are scored after `bylaw validate`, together with bylaw's own `.editorconfig` findings: the score is for what would be posted, not for the raw model output. The report also gives how many model findings the validator dropped.

## Running it

A model run calls the model once per case, so it costs money. Start with a few cases to see the cost per case:

```
bylaw eval run --provider anthropic --only py-sqli --out runs/opus
bylaw eval score --runs runs/opus --only py-sqli --label "claude-opus-5-5, 2026-10-15" --input-price <usd> --output-price <usd>
```

To cap the spend, add `--max-cost <usd> --input-price <usd> --output-price <usd>`: no new case starts once the saved runs in that directory cost that much. A hard limit for the whole account still belongs in the provider's console.

Every provider in [providers.md](../providers.md) runs the set the same way, with its own credentials in the environment, and each saved run records `provider:model:effort` as its reviewer, with `@<base URL>` added for a local server, since two servers can serve different weights under one model name. Bedrock, Vertex AI and Foundry bill at their own prices, so give those on the command line. A local model costs nothing and needs no key, so it is the cheapest way to try the set; write the model and the machine into the label, because a local result depends on both:

```
bylaw eval run --provider openai-compatible --base-url http://localhost:11434/v1 --model qwen3:4b --out runs/qwen3-4b
bylaw eval score --runs runs/qwen3-4b --label "qwen3:4b on Ollama, <CPU or GPU>, <date>"
```

Then run the whole set into the same directory. A rerun skips cases that already have a result and retries only the failed ones, so an interrupted run never pays twice. Each saved result records the reviewer and a hash of the case: a rerun with another model into the same directory is refused, and a case whose files changed is reviewed again. `score --only` scores only the matching cases, tokens and latency included.

Host models (Claude Code, Codex) review without an API key: `bylaw eval prepare --out host` writes `<id>.brief.txt` and `<id>.context.json` per case, the host writes `<id>.json` for each brief in the `bylaw schema` format, and `bylaw eval run --answers host --out runs/host` scores them like any other run.

`bylaw eval run --no-model` gives the baseline of a repository without a model key: bylaw's own checks only.

Prices are given on the command line, never stored in the code, because they change. Cost is per reviewed case and approximate: cached input is priced as plain input, and failed attempts are not counted. Latency is only reported for model runs; replayed host answers and `--no-model` have none.

Committed results live in `eval/results/<name>/`: the per-case runs and `report.md`. The runs of 15, 16 and 18 October 2026 were made before the five `py-mono` cases were added, so they cover the other 50. No committed model run includes the two `py-ledger` cases yet, nor the three `py-payments` cases; the checks-only baseline of 19 October 2026 (`eval/results/2026-10-19-checks-only-v0.6`) covers all 60.

## Real pull requests

The planted set's labels are certain but its changes are small and tidy. The second set, in `eval/real/`, holds real pull requests from permissively licensed projects, picked by the rules in [real-set.md](real-set.md) and frozen so a run never reads GitHub ([ADR 0015](../adr/0015-real-pull-request-set.md)). It holds 25 cases from 15 projects in Python, TypeScript, JavaScript and Go, about 2.3 MB in all. It is its own set root, so the commands are the same with `--set eval/real`:

```
bylaw eval run --set eval/real --no-model --out runs/real-checks
bylaw eval score --set eval/real --runs runs/real-checks --label "bylaw checks only, real set"
```

Each case is the pull request at the commit a reviewer commented on, with the files it touches at the merge base (`base/`) and at that commit (`head/`), the rule and spec files bylaw reads, the linked issue in `snapshot.json`, and the project's licence notice. The matching rules are the ones above. What differs is what a label means: it is a problem a reviewer named and the author fixed, so a finding elsewhere can be a real problem nobody reported, and real precision is a lower bound.

The report puts real cases in their own sections and never adds them to the planted numbers. A case two people have not labelled yet is reported under "provisional labels"; those numbers check the tooling, not the reviewer. How to label a case is in [labelling.md](labelling.md).

To add a pull request, freeze it with a GitHub token (read-only use; it is never stored):

```
GH_TOKEN="$(gh auth token)" bylaw eval snapshot --repo encode/httpx --pr 2423 --comment 1045653671 --id httpx-2423
```

`--comment` is the id of the review comment the case is built around; the snapshot is the commit it was made on. The tool refuses a project whose licence is not MIT, Apache-2.0 or BSD, and a snapshot whose diff does not match GitHub's. It writes no labels: add `case.toml` as [labelling.md](labelling.md) describes.
