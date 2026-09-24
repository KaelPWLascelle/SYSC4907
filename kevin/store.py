"""Single-device profile, transactional local SQLite storage."""
from pathlib import Path
import sqlite3

class FeedbackStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS feedback (content_id TEXT PRIMARY KEY, value INTEGER NOT NULL CHECK(value IN (-1,1)), updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def all(self):
        with self.connect() as db:
            return dict(db.execute('SELECT content_id, value FROM feedback'))

    def set(self, content_id, value):
        if type(value) is not int or value not in (-1, 0, 1):
            raise ValueError('Feedback must be -1, 0 (clear), or 1')
        with self.connect() as db:
            if value == 0:
                db.execute('DELETE FROM feedback WHERE content_id=?', (content_id,))
            else:
                db.execute('INSERT INTO feedback(content_id,value) VALUES (?,?) ON CONFLICT(content_id) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP', (content_id, value))
