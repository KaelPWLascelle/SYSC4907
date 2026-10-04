"""Data access for ratings and watch history. Routes use these; they never write SQL themselves."""
from dataclasses import dataclass
import math

COMPLETE_FRACTION = 0.9      # watched this share of the runtime: counts as finished
RESUME_MIN_SECONDS = 30      # shorter than this is an accidental start, not "continue watching"


class RatingsRepository:
    """Explicit like (1) / dislike (-1) per title. 0 clears a rating."""

    def __init__(self, database):
        self.db = database

    def all(self):
        with self.db.connect() as db:
            return dict(db.execute('SELECT content_id, value FROM feedback'))

    def set(self, content_id, value):
        if type(value) is not int or value not in (-1, 0, 1):
            raise ValueError('Feedback must be -1, 0 (clear), or 1')
        with self.db.connect() as db:
            if value == 0:
                db.execute('DELETE FROM feedback WHERE content_id = ?', (content_id,))
            else:
                db.execute('INSERT INTO feedback (content_id, value) VALUES (?, ?) '
                           'ON CONFLICT (content_id) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP',
                           (content_id, value))


@dataclass(frozen=True)
class Progress:
    content_id: str
    position_seconds: float
    duration_seconds: float
    completed: bool
    updated_at: str

    @property
    def resumable(self):
        return not self.completed and self.position_seconds >= RESUME_MIN_SECONDS


class WatchHistoryRepository:
    def __init__(self, database):
        self.db = database

    def save(self, content_id, position_seconds, duration_seconds):
        for value in (position_seconds, duration_seconds):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('Position and duration must be finite numbers')
        if duration_seconds <= 0 or position_seconds < 0:
            raise ValueError('Duration must be positive and position cannot be negative')
        position_seconds = min(position_seconds, duration_seconds)
        completed = position_seconds >= duration_seconds * COMPLETE_FRACTION
        with self.db.connect() as db:
            db.execute('INSERT INTO watch_history (content_id, position_seconds, duration_seconds, completed) VALUES (?, ?, ?, ?) '
                       'ON CONFLICT (content_id) DO UPDATE SET position_seconds = excluded.position_seconds, '
                       'duration_seconds = excluded.duration_seconds, completed = excluded.completed, '
                       "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                       (content_id, float(position_seconds), float(duration_seconds), int(completed)))
        return self.get(content_id)

    def get(self, content_id):
        with self.db.connect() as db:
            row = db.execute('SELECT content_id, position_seconds, duration_seconds, completed, updated_at '
                             'FROM watch_history WHERE content_id = ?', (content_id,)).fetchone()
        return _progress(row) if row else None

    def recent(self, limit=50):
        """Most recently watched first."""
        with self.db.connect() as db:
            rows = db.execute('SELECT content_id, position_seconds, duration_seconds, completed, updated_at '
                              'FROM watch_history ORDER BY updated_at DESC LIMIT ?', (limit,)).fetchall()
        return [_progress(row) for row in rows]

    def clear(self, content_id):
        with self.db.connect() as db:
            db.execute('DELETE FROM watch_history WHERE content_id = ?', (content_id,))


def _progress(row):
    content_id, position, duration, completed, updated_at = row
    return Progress(content_id, position, duration, bool(completed), updated_at)
