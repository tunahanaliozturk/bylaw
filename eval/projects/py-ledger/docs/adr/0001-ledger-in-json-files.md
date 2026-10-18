# 1. Keep the ledger in JSON files

Status: Superseded by [ADR 0002](0002-sqlite-through-the-store-module.md)

## Context

The first version had one user and a handful of entries.

## Decision

Entries are kept in one JSON file per month under `data/`, written by whichever module needs them. There
is no database.

## Consequences

Nothing to install, and nothing that survives two writers.
