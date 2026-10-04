# 0003. SQLite stays; schema changes go through numbered migrations

**Status:** Accepted

## Context
New features need new tables (watch history now; profiles and a larger catalogue later). The MVP
created its one table with `CREATE TABLE IF NOT EXISTS`, which cannot evolve a schema safely, and
users already have databases on disk.

## Decision
- SQLite remains the only database: embedded, single-file, no server, and it keeps data on the device.
  A server database (Postgres) or a cloud store would contradict ADR 0001.
- `flicks/db.py` owns connections (WAL, foreign keys, busy timeout) and an ordered list of
  migrations tracked with `PRAGMA user_version`. Each migration runs in a transaction; startup
  applies pending ones. Migration 1 adopts the MVP's existing `feedback` table unchanged.
- Data access goes through small repository classes, not SQL scattered through routes.
- No ORM for now: the schema is small and the SQL is clearer than the mapping layer.

## Consequences
Every schema change is a new numbered migration with a test that upgrades a database created by the
previous version. The catalogue stays a JSON file until it grows (MovieLens import), then moves to a
table with FTS5 search in its own migration.
