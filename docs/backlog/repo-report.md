# Per-repository report

Roadmap: Q4 in [ROADMAP.md](../ROADMAP.md). Target: v1.0. Item ids: `RPT-n`.

Show what bylaw found and what happened to it: findings by category, fix rate, criteria met over time.

**Done when** the Action can publish a static report page with light and dark PNG charts.

## Items

- [x] **RPT-1** (M) Report data from the outcome store. Done when: tests.
- [x] **RPT-2** (M) Static HTML report. Done when: snapshot test.
- [ ] **RPT-3** (S) Action option to publish to GitHub Pages or as an artifact. Done when: demo repository report.

## Notes

Reads the store from LRN. RPT-3's `report` input (artifact or GitHub Pages) and `bylaw report` are built
and tested against the fake GitHub; the box stays open until a report is published from the bylaw-demo
repository, which needs closed pull requests with learning on.
