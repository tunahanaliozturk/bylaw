# 2. SQLite, reached only through the store module

Status: Accepted, 2026-09-01. Supersedes 0001.

## Context

JSON files did not survive two writers. The first move to SQLite let every module open its own connection, which spread the schema and the connection settings across the code.

## Decision

The ledger lives in one SQLite database.
Only `ledger/store.py` opens connections and runs SQL; every other module calls the store's functions and never imports `sqlite3` itself.
A query another module needs becomes a new function in `ledger/store.py`.

## Consequences

- The schema and the connection settings live in one file.
- A report that needs a new query waits for a store function.
