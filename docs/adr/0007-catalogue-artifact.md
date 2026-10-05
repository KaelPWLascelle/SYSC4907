# 0007. The catalogue is a read-only build artifact, searched in memory

**Status:** Accepted · amends [0003](0003-sqlite-migrations.md), which expected the catalogue to move
into SQLite with FTS5 once it grew

## Context
Importing MovieLens grows the catalogue from 36 titles to about 9,700. Two things had to change:
the app sent the whole catalogue to the browser in `/api/state` and rendered all of it in Browse, and
ADR 0003 planned to move the catalogue into a database table with full-text search at this point.

## Decision
- **The catalogue stays a validated JSON file.** It is produced by an importer
  (`python -m flicks.datasets.movielens`) or bundled, never edited by the app, and rebuilt rather than
  migrated. SQLite holds only the user's own data (ratings, watch history), which does change and must
  be migrated.
- **Search runs in memory** (`flicks/search.py`): accent-insensitive, every word must match, over
  title, year, genres and tags, in catalogue order.
- **The browser never holds the catalogue.** `/api/state` reports its size and genres; Browse pages
  through `/api/titles`; `/api/history` includes each title's details; components pass title objects
  rather than looking titles up by ID.

## Alternatives considered
- **SQLite + FTS5 (the plan in 0003):** better ranking and prefix search, but it would mean migrating
  a derived dataset, keeping two copies in sync, and a second data path for the bundled catalogue.
  The importer would also have to write into the user's database.
- **Ship the catalogue to the browser and filter there:** simplest, but several megabytes of JSON on
  every page load, and a grid of thousands of titles.

## Consequences
Search is a linear scan over pre-normalized text. That is milliseconds at 10,000 titles (see
docs/evaluation.md); revisit FTS5 if a catalogue reaches hundreds of thousands of titles or needs
relevance ranking. Ratings attach to content IDs, so switching catalogues (bundled `m001…` vs
MovieLens `ml1…`) should use a separate `--db`.
