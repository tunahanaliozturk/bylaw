# Contributing

Thanks for helping. Open a pull request against `main` and keep it to one change.

## Rules

- Build SQL with parameters, never with string formatting or concatenation.
- Use the `logging` module for messages, never `print`.
- Never log personal data such as email addresses or names.
- Add no third-party dependency without an ADR in `docs/adr/`.
- Public functions have type hints on every argument and the return value.

## Tests

Run `python -m pytest`. Every change in behaviour comes with a test.
