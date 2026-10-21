"""Who is watching: profile sign-in on this machine, and moving a profile's data between devices.

docs/adr/0012-local-profiles.md. A profile separates the people in a household; it is not a security
boundary against someone who can read the database file, which is not encrypted.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
import threading
import time

from .repositories import checked_progress, instant, iso
from .text import normalize

COOKIE = 'flicks_profile'
FORMAT = 'flicks-profile'
FORMAT_VERSION = 1
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_ROWS = 50_000
MAX_FAILURES = 5             # wrong PINs in a row before a profile is locked for a while
LOCKOUT_SECONDS = 60


class Locked(PermissionError):
    pass


class ProfileSessions:
    """Random sign-in tokens held in memory: restarting Flicks signs everyone out of PIN profiles."""

    def __init__(self, clock=time.monotonic):
        self.tokens, self.failures, self.clock, self.lock = {}, {}, clock, threading.Lock()
        self.attempt_locks = {}  # profile ID -> lock serialising that profile's PIN attempts

    def start(self, profile_id):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.tokens[token] = profile_id
        return token

    def profile(self, token):
        with self.lock:
            return self.tokens.get(token) if token else None

    def end(self, token):
        with self.lock:
            self.tokens.pop(token, None)

    def forget_profile(self, profile_id):
        with self.lock:
            self.tokens = {t: p for t, p in self.tokens.items() if p != profile_id}
            self.failures.pop(profile_id, None)

    def attempt(self, profile_id, verify):
        """Run `verify()` (the slow PIN check) as one locked attempt for this profile; True if it passed.

        Attempts on one profile run one at a time, so parallel guesses cannot all slip in before the first
        failure is counted. Five failures in a row lock the profile for a minute; raises Locked meanwhile.
        """
        with self.lock:
            gate = self.attempt_locks.setdefault(profile_id, threading.Lock())
        with gate:
            with self.lock:
                count, until = self.failures.get(profile_id, (0, 0))
            now = self.clock()
            if count >= MAX_FAILURES and now < until:
                raise Locked(f'Too many wrong PINs. Try again in {int(until - now) + 1} seconds.')
            ok = verify()
            with self.lock:
                if ok:
                    self.failures.pop(profile_id, None)
                else:
                    count = 0 if count >= MAX_FAILURES else count  # the previous lockout has expired
                    self.failures[profile_id] = (count + 1, self.clock() + LOCKOUT_SECONDS)
            return ok


def export_profile(profile, ratings, history, by_id):
    """A portable, versioned document: ratings and progress keyed by ID, with title and year to re-match."""
    def describe(content_id):
        item = by_id.get(content_id)
        return {'title': item.title, 'year': item.year} if item else {}
    return {
        'format': FORMAT, 'version': FORMAT_VERSION,
        'exported_at': iso(datetime.now(timezone.utc)),
        'profile': {'name': profile.name},
        # The model is a pure function of the ratings, so ratings are the user's data; there are no weights to carry.
        'ratings': [{'id': cid, **describe(cid), 'value': value, 'updated_at': updated}
                    for cid, value, updated in ratings.rows()],
        'history': [{'id': p.content_id, **describe(p.content_id), 'position_seconds': p.position_seconds,
                     'duration_seconds': p.duration_seconds, 'updated_at': p.updated_at}
                    for p in history.recent(limit=MAX_ROWS)],
    }


@dataclass
class ImportPlan:
    name: str
    ratings: list    # (content_id, value, updated_at)
    history: list    # (content_id, position, duration, updated_at)
    skipped: int


def plan_import(document, catalog):
    """Validate an exported document and match its titles to this catalogue. Raises ValueError if malformed.

    A row matches by ID when that ID names the same film here; otherwise by exact title and year, so a
    profile moves between catalogues that number titles differently. Rows that match nothing are skipped.
    """
    if not isinstance(document, dict) or document.get('format') != FORMAT:
        raise ValueError('This is not a Flicks profile export')
    if document.get('version') != FORMAT_VERSION:
        raise ValueError(f'Unsupported export version {document.get("version")!r}; this Flicks reads version {FORMAT_VERSION}')
    unknown = set(document) - {'format', 'version', 'exported_at', 'profile', 'ratings', 'history'}
    if unknown:
        raise ValueError(f'Unknown fields in the export: {", ".join(sorted(unknown))}')
    profile = document.get('profile')
    if not isinstance(profile, dict) or not isinstance(profile.get('name'), str):
        raise ValueError('The export has no profile name')
    ratings, history = document.get('ratings', []), document.get('history', [])
    if not isinstance(ratings, list) or not isinstance(history, list) or len(ratings) + len(history) > MAX_ROWS:
        raise ValueError(f'Ratings and history must be lists of at most {MAX_ROWS} rows in total')
    by_id = {item.id: item for item in catalog}
    by_name = {}
    for item in catalog:
        by_name.setdefault((normalize(item.title), item.year), []).append(item.id)

    def match(row, fields):
        if not isinstance(row, dict) or set(row) - fields - {'id', 'title', 'year', 'updated_at'}:
            raise ValueError('Each row must be an object with known fields')
        content_id, title, year = row.get('id'), row.get('title'), row.get('year')
        same = by_id.get(content_id) if isinstance(content_id, str) else None
        if same and (title is None or (normalize(same.title) == normalize(str(title)) and same.year == year)):
            return same.id
        if isinstance(title, str) and type(year) is int:
            found = by_name.get((normalize(title), year), [])
            return found[0] if len(found) == 1 else None
        return None

    planned_ratings, planned_history, skipped = [], [], 0
    for row in ratings:
        content_id = match(row, {'value'})
        if row.get('value') not in (-1, 1) or type(row.get('value')) is not int:
            raise ValueError('Ratings must be 1 (like) or -1 (pass)')
        _timestamp(row)
        if content_id is None:
            skipped += 1
        else:
            planned_ratings.append((content_id, row['value'], row['updated_at']))
    for row in history:
        content_id = match(row, {'position_seconds', 'duration_seconds'})
        _timestamp(row)
        checked_progress(row.get('position_seconds'), row.get('duration_seconds'))  # every row, matched or not
        if content_id is None:
            skipped += 1
        else:
            planned_history.append((content_id, row.get('position_seconds'), row.get('duration_seconds'), row['updated_at']))
    return ImportPlan(profile['name'], planned_ratings, planned_history, skipped)


def _timestamp(row):
    try:
        instant(row.get('updated_at'))
    except (TypeError, ValueError) as error:
        raise ValueError(f'Each row needs an ISO 8601 updated_at timestamp ({error})') from None
