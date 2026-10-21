"""Data access for profiles, ratings and watch history. Routes use these; they never write SQL themselves.

Ratings and history belong to one profile (docs/adr/0012-local-profiles.md). A repository is bound to a
profile when it is made; `for_profile` gives the same repository for another one.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import math
import re
import secrets
import sqlite3

COMPLETE_FRACTION = 0.9      # watched this share of the runtime: counts as finished
RESUME_MIN_SECONDS = 30      # shorter than this is an accidental start, not "continue watching"
DEFAULT_PROFILE = 1          # created by migration 3; owns everything recorded before profiles existed
MAX_PROFILES = 8
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
PIN = re.compile(r'\d{4,8}')
# scrypt at n=2**14, r=8: about 16 MiB and tens of milliseconds, so guessing PINs offline is slow.
SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def instant(text):
    """An ISO 8601 UTC timestamp, from either format the database has used, as an aware datetime."""
    if not isinstance(text, str) or len(text) > 40:
        raise ValueError('Timestamps must be ISO 8601 text')
    try:
        value = datetime.fromisoformat(text.replace('Z', '+00:00').replace(' ', 'T'))
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    except OverflowError:
        raise ValueError('Timestamps must be between 1970 and 2200') from None
    if not 1970 <= value.year <= 2200:
        raise ValueError('Timestamps must be between 1970 and 2200')
    return value


def iso(value: datetime):
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + f'{value.microsecond // 1000:03d}Z'


def hash_pin(pin):
    if not isinstance(pin, str) or not PIN.fullmatch(pin):
        raise ValueError('A PIN is 4 to 8 digits')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode(), salt=salt, **SCRYPT)
    return f'scrypt${salt.hex()}${digest.hex()}'


def check_pin(pin, stored):
    if not isinstance(pin, str) or not stored:
        return False
    _, salt, digest = stored.split('$')
    return hmac.compare_digest(hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), **SCRYPT).hex(), digest)


@dataclass(frozen=True)
class Profile:
    id: int
    name: str
    locked: bool
    created_at: str


class ProfileRepository:
    """Local viewer profiles: a name and an optional PIN. Not an internet account; nothing leaves the device."""

    def __init__(self, database):
        self.db = database

    def all(self):
        with self.db.connect() as db:
            rows = db.execute('SELECT id, name, pin_hash, created_at FROM profiles ORDER BY id').fetchall()
        return [Profile(i, name, bool(pin), created) for i, name, pin, created in rows]

    def get(self, profile_id):
        return next((p for p in self.all() if p.id == profile_id), None)

    def default(self):
        """The profile requests use before anyone chooses one: the first without a PIN, or None."""
        return next((p for p in self.all() if not p.locked), None)

    def create(self, name, pin=None):
        name = _name(name)
        pin_hash = hash_pin(pin) if pin is not None else None
        with self.db.connect() as db:
            if db.execute('SELECT count(*) FROM profiles').fetchone()[0] >= MAX_PROFILES:
                raise ValueError(f'Flicks keeps at most {MAX_PROFILES} profiles')
            try:
                cursor = db.execute('INSERT INTO profiles (name, pin_hash) VALUES (?, ?)', (name, pin_hash))
            except sqlite3.IntegrityError:
                raise ValueError(f'There is already a profile called “{name}”') from None
        return self.get(cursor.lastrowid)

    def unique_name(self, name):
        """`name`, or `name (2)`, `name (3)`… so an import never collides with an existing profile."""
        base = _name(name)[:34]
        taken = {p.name.casefold() for p in self.all()}
        candidate, n = base, 2
        while candidate.casefold() in taken:
            candidate, n = f'{base} ({n})', n + 1
        return candidate

    def rename(self, profile_id, name):
        name = _name(name)
        try:
            with self.db.connect() as db:
                db.execute('UPDATE profiles SET name = ? WHERE id = ?', (name, profile_id))
        except sqlite3.IntegrityError:
            raise ValueError(f'There is already a profile called “{name}”') from None

    def set_pin(self, profile_id, pin):
        """pin None removes the PIN."""
        with self.db.connect() as db:
            db.execute('UPDATE profiles SET pin_hash = ? WHERE id = ?', (hash_pin(pin) if pin is not None else None, profile_id))

    def verify(self, profile_id, pin):
        with self.db.connect() as db:
            row = db.execute('SELECT pin_hash FROM profiles WHERE id = ?', (profile_id,)).fetchone()
        if row is None:
            return False
        return row[0] is None or check_pin(pin, row[0])

    def delete(self, profile_id):
        """Deletes the profile and, through the foreign keys, its ratings and history. Keeps at least one."""
        with self.db.connect() as db:
            if db.execute('SELECT count(*) FROM profiles').fetchone()[0] <= 1:
                raise ValueError('Flicks needs at least one profile. Clear its data instead.')
            db.execute('DELETE FROM profiles WHERE id = ?', (profile_id,))


def _name(name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or any(ord(c) < 32 for c in name):
        raise ValueError('A profile name is 1 to 40 characters')
    return ' '.join(name.split())


class RatingsRepository:
    """Explicit like (1) / dislike (-1) per title. 0 clears a rating."""

    def __init__(self, database, profile_id=DEFAULT_PROFILE):
        self.db, self.profile_id = database, profile_id

    def for_profile(self, profile_id):
        return RatingsRepository(self.db, profile_id)

    def all(self):
        with self.db.connect() as db:
            return dict(db.execute('SELECT content_id, value FROM feedback WHERE profile_id = ?', (self.profile_id,)))

    def rows(self):
        """(content_id, value, updated_at) for export."""
        with self.db.connect() as db:
            return db.execute('SELECT content_id, value, updated_at FROM feedback WHERE profile_id = ? ORDER BY content_id',
                              (self.profile_id,)).fetchall()

    def set(self, content_id, value):
        if type(value) is not int or value not in (-1, 0, 1):
            raise ValueError('Feedback must be -1, 0 (clear), or 1')
        with self.db.connect() as db:
            if value == 0:
                db.execute('DELETE FROM feedback WHERE profile_id = ? AND content_id = ?', (self.profile_id, content_id))
            else:
                db.execute('INSERT INTO feedback (profile_id, content_id, value) VALUES (?, ?, ?) '
                           f'ON CONFLICT (profile_id, content_id) DO UPDATE SET value = excluded.value, updated_at = {NOW}',
                           (self.profile_id, content_id, value))

    def clear_all(self):
        with self.db.connect() as db:
            db.execute('DELETE FROM feedback WHERE profile_id = ?', (self.profile_id,))


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
    def __init__(self, database, profile_id=DEFAULT_PROFILE):
        self.db, self.profile_id = database, profile_id

    def for_profile(self, profile_id):
        return WatchHistoryRepository(self.db, profile_id)

    def save(self, content_id, position_seconds, duration_seconds):
        position_seconds, duration_seconds, completed = checked_progress(position_seconds, duration_seconds)
        with self.db.connect() as db:
            db.execute('INSERT INTO watch_history (profile_id, content_id, position_seconds, duration_seconds, completed) '
                       'VALUES (?, ?, ?, ?, ?) '
                       'ON CONFLICT (profile_id, content_id) DO UPDATE SET position_seconds = excluded.position_seconds, '
                       'duration_seconds = excluded.duration_seconds, completed = excluded.completed, '
                       f'updated_at = {NOW}',
                       (self.profile_id, content_id, position_seconds, duration_seconds, int(completed)))
        return self.get(content_id)

    def get(self, content_id):
        with self.db.connect() as db:
            row = db.execute('SELECT content_id, position_seconds, duration_seconds, completed, updated_at '
                             'FROM watch_history WHERE profile_id = ? AND content_id = ?', (self.profile_id, content_id)).fetchone()
        return _progress(row) if row else None

    def recent(self, limit=50):
        """Most recently watched first."""
        with self.db.connect() as db:
            rows = db.execute('SELECT content_id, position_seconds, duration_seconds, completed, updated_at '
                              'FROM watch_history WHERE profile_id = ? ORDER BY updated_at DESC LIMIT ?',
                              (self.profile_id, limit)).fetchall()
        return [_progress(row) for row in rows]

    def clear(self, content_id):
        with self.db.connect() as db:
            db.execute('DELETE FROM watch_history WHERE profile_id = ? AND content_id = ?', (self.profile_id, content_id))

    def clear_all(self):
        with self.db.connect() as db:
            db.execute('DELETE FROM watch_history WHERE profile_id = ?', (self.profile_id,))


def merge_profile_data(database, profile_id, ratings, history):
    """Import ratings and progress in one transaction: either all of it lands or none does."""
    with database.connect() as db:
        return _merge_ratings(db, profile_id, ratings), _merge_history(db, profile_id, history)


def _merge_ratings(db, profile_id, rows):
    changed = 0
    for content_id, value, updated_at in rows:
        current = db.execute('SELECT updated_at FROM feedback WHERE profile_id = ? AND content_id = ?',
                             (profile_id, content_id)).fetchone()
        if current and instant(current[0]) >= instant(updated_at):
            continue
        db.execute('INSERT INTO feedback (profile_id, content_id, value, updated_at) VALUES (?, ?, ?, ?) '
                   'ON CONFLICT (profile_id, content_id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at',
                   (profile_id, content_id, value, iso(instant(updated_at))))
        changed += 1
    return changed


def _merge_history(db, profile_id, rows):
    changed = 0
    for content_id, position, duration, updated_at in rows:
        position, duration, completed = checked_progress(position, duration)
        current = db.execute('SELECT updated_at FROM watch_history WHERE profile_id = ? AND content_id = ?',
                             (profile_id, content_id)).fetchone()
        if current and instant(current[0]) >= instant(updated_at):
            continue
        db.execute('INSERT INTO watch_history (profile_id, content_id, position_seconds, duration_seconds, completed, updated_at) '
                   'VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (profile_id, content_id) DO UPDATE SET '
                   'position_seconds = excluded.position_seconds, duration_seconds = excluded.duration_seconds, '
                   'completed = excluded.completed, updated_at = excluded.updated_at',
                   (profile_id, content_id, position, duration, int(completed), iso(instant(updated_at))))
        changed += 1
    return changed


def checked_progress(position_seconds, duration_seconds):
    for value in (position_seconds, duration_seconds):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Position and duration must be finite numbers')
    if duration_seconds <= 0 or position_seconds < 0:
        raise ValueError('Duration must be positive and position cannot be negative')
    position_seconds = float(min(position_seconds, duration_seconds))
    return position_seconds, float(duration_seconds), position_seconds >= duration_seconds * COMPLETE_FRACTION


def _progress(row):
    content_id, position, duration, completed, updated_at = row
    return Progress(content_id, position, duration, bool(completed), updated_at)
