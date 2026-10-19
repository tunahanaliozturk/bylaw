# Files written by bylaw 0.x

tests/unit/test_compatibility.py reads these to prove that a release does not break what earlier releases
wrote (V1-3, docs/compatibility.md). They are real output, not hand-written, so they carry whatever quirks
the old code had. Never edit one to make a test pass: a failing test here means the new code broke a
file people already have.

- `0.1.1/cs-async-void.context.json`: `bylaw eval prepare --only cs-async-void` run from the v0.1.1 tag.
- `0.1.1/cs-async-void.run.json`: copied from eval/results/2026-10-16-claude-code-host, the result Claude
  Code wrote as host on v0.1.x, saved by `bylaw eval run`.
- `0.2.0/cs-async-void.context.json`: the same case prepared from the v0.2.0 tag.
- `0.2.0/summary.md` and `0.2.0/threads.json`: the summary comment and inline comment bodies v0.2.0's
  `publish` wrote for that case, with one thread resolved as fixed and a review memory in the state.
- `0.6.0/py-iso-logs-password.context.json`: `bylaw eval prepare` from v0.6.0, a case with the
  `iso27001` profile on.
- `0.6.0/py-iso-logs-password.run.json`: copied from eval/results/2026-10-19-opus-5-5-v0.6.
- `0.6.0/evidence.json`: the evidence v0.6.0 builds from that context and result, stamped the way
  `bylaw review --evidence` stamps it.
- `0.6.0/bylaw.toml`: every key 0.6.0 reads, before `version` existed.

To add a release, generate its files with that release's tag, not with the current code.
