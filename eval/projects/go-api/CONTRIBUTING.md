# Contributing

Run `go test ./...` and `go vet ./...` before opening a pull request.

## Rules

- Wrap errors with `%w` so callers can inspect them.
- Pass `context.Context` as the first argument of anything that does I/O.
- Never `panic` in a handler; log the error and return an error status.
- Queries use placeholders, never `fmt.Sprintf`.
