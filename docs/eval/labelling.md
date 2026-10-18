# Labelling real pull requests

Each real case needs labels from two people who label it on their own, then compare. Until then the case is provisional: the report shows it in its own section and nobody quotes its numbers. A model wrote a first pass for every case (`labellers = ["first pass (model)"]`). Treat it as a draft to check, not as one of the two labels.

## What you work from

A case lives in `eval/real/cases/<id>/`:

- `snapshot.json`: the pull request as the reviewer saw it. `url` and `head_sha` take you to the reviewed commit on GitHub, `evidence` is the review comment the case was picked for, and `issues` holds the linked issue text bylaw reads.
- `base/` and `head/`: the files the change touches, at the merge base and at the reviewed commit, plus the rule and spec files bylaw reads.
- `LICENSE` (or the project's own licence file name) and, for Apache projects, `NOTICE`: keep them.
- `case.toml`: the labels. The format is the planted one ([README.md](README.md#labels)) plus two keys described below.

To see the diff bylaw reviews, build the case and print its context:

```
bylaw eval prepare --set eval/real --only <id> --out /tmp/brief
```

`<id>.brief.txt` is exactly what a reviewer model reads, with line numbers.

## How to label

1. **Read the issue first**, then the diff, then the review comment. Decide what the change was meant to do before you look at what someone found.
2. **Label the problem the comment names.** One `[[findings]]` entry at the lines the comment points at, at the reviewed commit. Choose the categories that count as right: a problem can be both a `bug` and a `rule` break. Write the `note` in your own words. Check the fix commit (the next commit that changes those lines) to make sure the comment was about what you think.
3. **Label other real problems you are sure of**, the same way. Be strict: a label says "a good reviewer must find this". If you would not block a merge over it, it is not a label.
4. **Mark the rest of the added code as `[[allowed]]`.** A fair remark on code the change adds is not a false alarm on a real pull request; nobody checked every line. Leave unchanged context and untouched files out of `allowed`.
5. **Criteria.** If the issue has acceptance criteria bylaw extracts (`issue#<n>/AC-<k>`), give each the statuses that count as right at the reviewed commit. If you are unsure, leave the criterion out rather than guessing.
6. **Kind.** `bug`, `security`, `rule`, `requirement` or `scope`, by the main label. A real case is never `clean`: a reviewer found something.
7. **Add yourself** to `labellers`, and remove `"first pass (model)"` once your labels replace the draft.

Label on your own. Do not read the other labeller's file or the first pass until you have written yours; each of you starts from a copy of the case with the labels removed.

## Comparing and recording disagreements

When both of you are done, compare entry by entry. Agree on one `case.toml` and record every place you differed, even when it was easy to settle, because the disagreement rate is part of what the set measures:

```toml
labellers = ["ada", "grace"]

[[disagreements]]
about = "src/retry.py:41-44"
views = { ada = "bug: retries forever when max is 0", grace = "allowed: max 0 is documented as unlimited" }
resolution = "allowed; the docstring says 0 means no limit"
```

- `about`: the file and lines, a criterion key, or `kind`.
- `views`: what each labeller said, keyed by the names in `labellers`. A name that is not a labeller fails the build.
- `resolution`: what the case says now, and why.

A case with two names in `labellers` and no `"first pass (model)"` is final. The report then counts it under "Real pull requests" instead of the provisional section.

## Checks that run on every build

`tests/integration/test_eval_real_set.py` builds every real case and replays its labels as a reviewer would. A label on a line the change does not add, or a criterion key bylaw does not collect, fails it. The same test checks each case still carries its licence notice.
