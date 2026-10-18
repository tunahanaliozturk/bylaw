# API package

- Handlers never raise to the caller. A failure is returned as a `Result` with `ok=False` and an `error` message, so the HTTP layer can turn it into a response.
