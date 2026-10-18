# Evaluation set v2: real pull requests

Roadmap: Q2 in [ROADMAP.md](../ROADMAP.md). Target: v0.4. Item ids: `EV2-n`.

The planted set has certain labels but little realism (ADR 0010). Add real pull requests next to it.

**Done when** 20 to 30 real pull requests labelled by two people, reported apart from the planted set.

## Items

- [x] **EV2-1** (S) Selection rules: merged pull requests with a linked issue and a review comment that led to a fix. Done when: written rules ([real-set.md](../eval/real-set.md)).
- [x] **EV2-2** (M) Snapshot tool that freezes base, head and issue text into a case, so runs never fetch live data. Done when: tool and tests (`bylaw eval snapshot`, `tests/integration/test_eval_snapshot.py`).
- [ ] **EV2-3** (L) Label 20 to 30 pull requests with two labellers; record disagreements. Done when: cases committed.
- [x] **EV2-4** (S) Report the planted and real sets separately. Done when: report sections (planted, real, and real with provisional labels; `tests/unit/test_eval_report.py`).

## Notes

Only permissively licensed projects; each case keeps its licence notice.
