"""SQLite connections and schema migrations (see docs/adr/0003-sqlite-migrations.md).

Migrations are append-only: never edit one that has shipped; add the next number instead.
`PRAGMA user_version` records how many have been applied.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

MIGRATIONS = (
    # 1: ratings. IF NOT EXISTS lets databases created before migrations existed adopt it as-is.
    """
    CREATE TABLE IF NOT EXISTS feedback (
        content_id TEXT PRIMARY KEY,
        value INTEGER NOT NULL CHECK (value IN (-1, 1)),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 2: playback progress, one row per title (ADR 0005).
    """
    CREATE TABLE watch_history (
        content_id TEXT PRIMARY KEY,
        position_seconds REAL NOT NULL CHECK (position_seconds >= 0),
        duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
        completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
        started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))  -- ms precision orders rapid saves
    );
    CREATE INDEX watch_history_updated ON watch_history (updated_at DESC);
    """,
    # 3: local profiles (docs/adr/0012-local-profiles.md). Ratings and progress become per profile; existing
    # rows move to profile 1. Timestamps become ISO 8601 UTC with milliseconds so exports compare cleanly.
    """
    CREATE TABLE profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,  -- never reuse an ID: an open page names its profile by ID
        name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) BETWEEN 1 AND 40),
        pin_hash TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    INSERT INTO profiles (id, name) VALUES (1, 'Me');
    CREATE TABLE feedback_v3 (
        profile_id INTEGER NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
        content_id TEXT NOT NULL,
        value INTEGER NOT NULL CHECK (value IN (-1, 1)),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        PRIMARY KEY (profile_id, content_id)
    );
    INSERT INTO feedback_v3 (profile_id, content_id, value, updated_at)
        SELECT 1, content_id, value,
               CASE WHEN length(updated_at) = 19 THEN replace(updated_at, ' ', 'T') || '.000Z' ELSE updated_at END
        FROM feedback;
    DROP TABLE feedback;
    ALTER TABLE feedback_v3 RENAME TO feedback;
    CREATE TABLE watch_history_v3 (
        profile_id INTEGER NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
        content_id TEXT NOT NULL,
        position_seconds REAL NOT NULL CHECK (position_seconds >= 0),
        duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
        completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
        started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        PRIMARY KEY (profile_id, content_id)
    );
    INSERT INTO watch_history_v3 (profile_id, content_id, position_seconds, duration_seconds, completed, started_at, updated_at)
        SELECT 1, content_id, position_seconds, duration_seconds, completed, started_at, updated_at FROM watch_history;
    DROP TABLE watch_history;
    ALTER TABLE watch_history_v3 RENAME TO watch_history;
    CREATE INDEX watch_history_updated ON watch_history (profile_id, updated_at DESC);
    """,
)
SCHEMA_VERSION = len(MIGRATIONS)


class Database:
    """Opens short-lived connections; safe to share across threads (each call gets its own)."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self):
        """A connection inside a transaction: committed on success, rolled back on error, always closed."""
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute('PRAGMA busy_timeout = 10000')
            with connection:
                yield connection
        finally:
            connection.close()

    def version(self):
        with self.connect() as db:
            return db.execute('PRAGMA user_version').fetchone()[0]

    def migrate(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)  # explicit transactions
        try:
            connection.execute('PRAGMA journal_mode = WAL')
            current = connection.execute('PRAGMA user_version').fetchone()[0]
            if current > SCHEMA_VERSION:
                raise RuntimeError(f'{self.path} was created by a newer Flicks (schema {current}); upgrade Flicks to open it')
            for number in range(current + 1, SCHEMA_VERSION + 1):
                connection.execute('BEGIN IMMEDIATE')
                try:
                    for statement in _statements(MIGRATIONS[number - 1]):
                        connection.execute(statement)
                    connection.execute(f'PRAGMA user_version = {number}')
                    connection.execute('COMMIT')
                except BaseException:
                    connection.execute('ROLLBACK')
                    raise
        finally:
            connection.close()


def _statements(script):
    """Split a migration into statements so each runs inside our transaction (executescript would commit)."""
    return [s.strip() for s in script.split(';') if s.strip()]
