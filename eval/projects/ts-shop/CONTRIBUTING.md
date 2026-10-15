# Contributing

Open a pull request against `main`; CI runs `npm test` and `tsc --noEmit`.

## Rules

- Keep money in integer cents. Never use floating point for prices or totals.
- Log with `logger` from `src/logger.ts`, never `console.log`.
- Do not use `any`; type the value, or use `unknown` and narrow it.
- Every handler that reads or changes an order checks that the order belongs to the signed-in user.
- Await every promise before responding.
