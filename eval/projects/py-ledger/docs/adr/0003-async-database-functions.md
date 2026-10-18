# 3. Async functions for everything that touches the database

Status: Proposed

## Context

We may serve the ledger over HTTP one day.

## Decision

Every function that reads or writes the database is an `async` function.
