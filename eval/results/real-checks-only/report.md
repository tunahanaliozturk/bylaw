# Evaluation: bylaw checks only, no model, real set, 2026-10-18

## Real pull requests: provisional labels

Real pull requests, frozen at the commit a reviewer commented on (ADR 0015). Scored with the same
rules, never added to the planted numbers: labels say what a reviewer found and the author fixed, so
a false alarm here can be a problem nobody reported.

25 cases, labelled by fewer than two people (a model's first pass counts as nobody).
These numbers check the tooling, not the reviewer; quote none of them.

25 cases. Matching rules: docs/eval/README.md.

False alarms count findings on clean pull requests and outside the code a case adds; remarks on
labelled code that are not the labelled defect are listed separately, not counted.

| Category | Hits | False alarms | Misses | Precision | Recall |
| --- | --- | --- | --- | --- | --- |
| security | 0 | 0 | 2 | n/a | 0% |
| bug | 0 | 0 | 22 | n/a | 0% |
| rule | 0 | 0 | 1 | n/a | 0% |
| requirement | 0 | 0 | 0 | n/a | n/a |

- Labelled defects found at the right place, any category: 0 of 25.
- Clean pull requests with an inline comment (medium or above): 0 of 0.
- Model findings the validator dropped: 0 of 0.
- Duplicate findings: 0.
- Other remarks on labelled code, not scored: 0 (0 at medium or above).
- Rule findings citing the right rule line: 0 of 0.
- Acceptance criteria judged correctly: 0 of 0.
- Scope creep found: 0 of 0, with 0 extra.

### Misses

- bubbletea-1836: The 80x24 fallback size was applied even when output was not a terminal at all (buffer, pipe, SSH session), changing the old 0x0 behaviour for those apps.
- cli-13068: The new recovery hint dropped the hostname, so users on a non-default host were told to run plain gh auth login.
- cli-13946: The --worktree value was passed to git worktree add without an end-of-options marker, so a path starting with - would be parsed as a git flag.
- cli-9198: The parser used a custom readLine built on bufio.Reader.ReadLine, which can return partial lines for long input, as the Go docs warn.
- client_golang-1318: The handler relied on a shared package-level emptyLabels map that callers could write to, so labels could leak between uses and the name became misleading.
- cobra-2023: The new errPrefix field was printed directly, so commands that never set it printed an empty prefix instead of the default "Error:".
- echo-2380: ToMiddleware() returned only a middleware and could not report config errors, unlike the other ToMiddleware methods in the package.
- fastify-6013: The guard read reply.request.socket.destroyed without checking the socket, but the socket can be undefined, which throws.
- fastify-6308: The error handler's error parameter was typed as Error, but anything thrown in a route, including non-Error values, can reach it.
- fastify-6483: The validator result was copied only when ret.value !== undefined, so a validator that legitimately coerced a value to undefined was ignored.
- fiber-4199: AllowedHostsFunc ran before the static rules, which contradicts the docs and the CORS pattern it claims to mirror and calls a possibly expensive function on every request.
- h3-1026: Header merging only handled Headers instances and plain objects, so an array-of-tuples HeadersInit was mishandled.
- h3-1202: ws.ts re-exported crossws types under generic names like Hooks and Peer instead of prefixing them as h3 types.
- h3-1329: Invalid Referer values were caught and silently ignored with an empty catch, hiding real errors.
- hono-4469: The binary-detection regex matched any content type containing xml, so the Office types from the issue (application/vnd.openxmlformats-...) were still served as text.
- hono-4792: shouldDeDupeByKey kept a props parameter it never used, which the project's lint rules flag.
- hono-4834: The value returned by the user's classNameSlug callback went into the class attribute and CSS selector unescaped, so a slug with spaces or braces could break or inject CSS.
- httpx-2423: The line decoder only treated a trailing \n as a line end, so text ending in \r or another str.splitlines separator was buffered and emitted late.
- httpx-2716: The transport imported SOCKET_OPTION from httpcore.backends.base, an undocumented private module of a dependency.
- ky-559: The PR still fell back to credentials 'same-origin', but the issue (Cloudflare Workers) needs credentials left unset when they are unsupported.
- starlette-2767: The test sent a message on a line that was never reached, so it did not test what it claimed.
- undici-5546: The test registered cleanup with the global after() instead of the test context's t.after(), against the suite's convention.
- vite-22468: plugin-legacy changed its minify behaviour without checking the Vite version, so an old Vite with the new plugin (or the reverse) would break.
- vite-22611: The code compared exports[key] === null where the project's lint rule wants == null so undefined is caught too.
- vite-23185: The build plugin resolved dynamic import variables with its own inline resolver, different from the one used in dev, so dev and build could resolve differently.
