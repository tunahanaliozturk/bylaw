# Incremental review: input on a second push

Each case is reviewed once; then one comment line is added to its smallest changed file and it is reviewed again, in full and incrementally. Input tokens are estimated from characters (3 per token, system prompt included); no model was called. Script: `tools/incremental_saving.py`.

| Case | Changed files | Full review | Incremental | Saved |
| --- | --- | --- | --- | --- |
| cs-async-void | 2 | 2,503 | 2,417 | 3% |
| cs-creep-discount | 3 | 2,556 | 2,105 | 18% |
| go-clean-handler | 3 | 2,641 | 2,223 | 16% |
| go-creep-timeout | 3 | 2,430 | 2,311 | 5% |
| go-panic-handler | 2 | 2,832 | 2,679 | 5% |
| go-req-not-found | 4 | 2,892 | 2,361 | 18% |
| py-clean-contained-path | 2 | 2,185 | 2,039 | 7% |
| py-clean-feature-tested | 2 | 2,616 | 2,509 | 4% |
| py-clean-param-sql | 2 | 2,692 | 2,534 | 6% |
| py-creep-token-lifetime | 3 | 2,133 | 2,006 | 6% |
| py-path-traversal | 2 | 2,413 | 2,265 | 6% |
| py-req-met | 3 | 3,107 | 2,829 | 9% |
| py-req-untested | 3 | 2,410 | 2,148 | 11% |
| ts-clean-feature | 2 | 2,590 | 2,347 | 9% |
| ts-creep-shipping | 3 | 2,479 | 2,352 | 5% |
| ts-missing-ownership | 2 | 2,522 | 2,275 | 10% |
| ts-req-met | 3 | 2,975 | 2,543 | 15% |
| **All 17 cases** | | **43,976** | **39,943** | **9%** |

The system prompt is sent on every run, so a second push always costs at least that much. The evaluation cases are small; on a long pull request the unchanged files are a larger share and the saving grows with them.
