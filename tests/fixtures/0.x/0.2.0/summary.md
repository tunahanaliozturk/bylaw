<!-- bylaw:summary -->

## bylaw review

Reviewed `38c125c` against `bc55d85`: 1 high. 0 new inline comments this run, 1 thread(s) resolved.

### Requirements

No linked issue or spec was found.

<details><summary>Rule sources (2)</summary>

- `.editorconfig`
- `CONTRIBUTING.md`

</details>

<sub>Model tokens: 48,210 this run, 48,210 on this pull request.</sub>

<!-- bylaw:state {"auto_resolved": ["PRRT_fixed"], "review": {"head_sha": "38c125c95f1ecd4dea6fdcc7c7c4d41c114d7c46", "inputs": "6467d0fc937ad421", "files": {"OrderService.cs": "0bbab1e7e4705cef", "OrdersController.cs": "d3bd65b1b7b8298a"}, "findings": [{"file": "OrderService.cs", "line_start": 22, "line_end": 22, "category": "bug", "severity": "high", "message": "NotifyAsync is `async void`, so the caller cannot await it and any exception it throws (for example ObjectDisposedException once the request-scoped DbContext is disposed) is raised on the thread pool and crashes the process.", "suggestion": "    public async Task NotifyAsync(Order order)", "evidence": null}], "criteria": [], "scope_creep": [], "criteria_since": {}, "tokens": 48210, "run_tokens": 48210}} -->