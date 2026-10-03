"""Couch mode: phones on the same Wi-Fi join by QR code, vote on a shortlist and act as a remote.

Privacy model:
- Off unless Flicks starts with --couch. The host server stays on 127.0.0.1 and keeps every
  existing route (feedback, voice, commands). Guests reach a *separate* server that listens on the
  local network only while a session runs and exposes only join, vote, remote and its own page.
- Only private-network (or loopback) addresses are accepted, never a public interface.
- Joining needs the code shown on the TV. Wrong guesses rotate the code. Each guest then gets a
  random token sent in a header, so every later request is authenticated and cannot be forged by
  another web page (custom headers force a CORS preflight, which this server never approves).
- Guests see public catalogue fields only: never the host's ratings, history or taste factors.
  Names and votes live in memory and are discarded when the session ends.
"""
from dataclasses import dataclass, field
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import threading
import time

from . import qr

STATIC = Path(__file__).parent/'static'
CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # no 0/O, 1/I/L
CODE_LENGTH = 8
MAX_FAILED_JOINS = 10
MAX_GUESTS = 8
SESSION_SECONDS = 3 * 60 * 60
PUBLIC_FIELDS = ('id', 'title', 'year', 'minutes', 'genres', 'moods', 'intensity', 'description')
PLAYER_ACTIONS = ('play', 'pause', 'stop', 'select')


class CouchError(ValueError):
    """A request a guest or host can fix (bad code, unknown title, session full...)."""


class CouchAuthError(CouchError):
    """Missing or wrong guest token."""


def new_code():
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def token_key(token):
    return hashlib.sha256(token.encode()).hexdigest()


def check_host(address):
    """Accept private-network and loopback IPv4 addresses only."""
    try:
        ip = ipaddress.IPv4Address(address)
    except ValueError:
        raise CouchError('Couch mode needs an IPv4 address on your home network, e.g. 192.168.1.23') from None
    if not (ip.is_private or ip.is_loopback) or ip.is_unspecified or ip.is_link_local:
        raise CouchError('Couch mode only listens on a private home network address, never a public one')
    return str(ip)


def lan_address():
    """This machine's address on the local network. A UDP connect picks a route and sends nothing."""
    candidates = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(('192.0.2.1', 9))  # TEST-NET-1: never routed to a real host
            candidates.append(s.getsockname()[0])
        except OSError:
            pass
    try:
        candidates.append(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    for address in candidates:
        try:
            if not ipaddress.IPv4Address(address).is_loopback:
                return check_host(address)
        except (ValueError, CouchError):
            continue
    raise CouchError('No home network found. Connect to Wi-Fi or start Flicks with --couch-host <address>')


def normalize_name(name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 24 or not name.strip().isprintable():
        raise CouchError('Pick a name of 1–24 characters')
    return ' '.join(name.split())


@dataclass
class Guest:
    id: str
    name: str
    votes: dict = field(default_factory=dict)


class CouchSession:
    """In-memory state for one couch session. Thread-safe; no network or persistence."""

    def __init__(self, shortlist, clock=time.monotonic, seconds=SESSION_SECONDS):
        if len(shortlist) < 2:
            raise CouchError('Couch mode needs at least two titles to vote on; widen the scene settings')
        self.items = [{k: row['content'][k] for k in PUBLIC_FIELDS} for row in shortlist]
        self.order = {item['id']: rank for rank, item in enumerate(self.items)}  # Flicks' ranking
        self.clock, self.expires = clock, clock() + seconds
        self.code, self.failed_joins = new_code(), 0
        self.guests = {}  # sha256(token) -> Guest
        self.revealed = False
        self.player = {'id': None, 'state': 'stopped', 'by': None}
        self.version = 0
        self.lock = threading.Lock()

    def expired(self):
        return self.clock() >= self.expires

    def _changed(self):
        self.version += 1

    def join(self, code, name):
        with self.lock:
            if self.expired():
                raise CouchError('This couch session has ended')
            if not isinstance(code, str) or not secrets.compare_digest(code.strip().upper().encode(), self.code.encode()):
                self.failed_joins += 1
                if self.failed_joins >= MAX_FAILED_JOINS:
                    self.code, self.failed_joins = new_code(), 0  # the TV shows the new code
                    self._changed()
                raise CouchAuthError('That code does not match the one on the TV')
            if len(self.guests) >= MAX_GUESTS:
                raise CouchError(f'This session is full ({MAX_GUESTS} people)')
            name = normalize_name(name)
            taken = {g.name for g in self.guests.values()}
            base, n = name, 2
            while name in taken:
                name, n = f'{base} {n}', n + 1
            token = secrets.token_urlsafe(24)
            guest = Guest(secrets.token_hex(4), name)
            self.guests[token_key(token)] = guest
            self._changed()
            return token, guest

    def guest(self, token):
        if not isinstance(token, str) or not token or self.expired():
            raise CouchAuthError('Join the couch session first')
        guest = self.guests.get(token_key(token))
        if guest is None:
            raise CouchAuthError('Join the couch session first')
        return guest

    def vote(self, token, content_id, value):
        with self.lock:
            guest = self.guest(token)
            if content_id not in self.order:
                raise CouchError('That title is not on this shortlist')
            if type(value) is not int or value not in (-1, 0, 1):
                raise CouchError('Vote must be 1 (yes), -1 (no) or 0 (clear)')
            if value:
                guest.votes[content_id] = value
            else:
                guest.votes.pop(content_id, None)
            if not self.revealed and self.guests and all(len(g.votes) == len(self.items) for g in self.guests.values()):
                self.revealed = True  # everyone has finished: show the results
            self._changed()

    def reveal(self):
        with self.lock:
            self.revealed = True
            self._changed()

    def control(self, action, content_id=None, by='Host'):
        """Player stub: records what the TV should do. Real playback will subscribe to this state."""
        with self.lock:
            if action not in PLAYER_ACTIONS:
                raise CouchError('Unknown remote action')
            if action == 'select':
                if content_id not in self.order:
                    raise CouchError('That title is not on this shortlist')
                self.player = {'id': content_id, 'state': 'playing', 'by': by}
            elif self.player['id'] is None:
                raise CouchError('Pick a title to play first')
            else:
                self.player = {**self.player, 'state': {'play': 'playing', 'pause': 'paused', 'stop': 'stopped'}[action], 'by': by}
            self._changed()

    def remote(self, token, action, content_id=None):
        with self.lock:
            name = self.guest(token).name
        self.control(action, content_id, by=name)

    def results(self):
        """Approval voting: most yeses, then fewest nos, then Flicks' own ranking breaks ties."""
        rows = []
        voters = list(self.guests.values())
        for item in self.items:
            yes = sum(g.votes.get(item['id']) == 1 for g in voters)
            no = sum(g.votes.get(item['id']) == -1 for g in voters)
            rows.append({'id': item['id'], 'yes': yes, 'no': no, 'flicks_rank': self.order[item['id']] + 1,
                         'match': bool(voters) and yes == len(voters)})
        return sorted(rows, key=lambda r: (-r['yes'], r['no'], r['flicks_rank']))

    def _common(self):
        return {'active': True, 'version': self.version, 'items': self.items, 'revealed': self.revealed,
                'player': self.player, 'expires_in': max(0, round(self.expires - self.clock())),
                'progress': [{'name': g.name, 'voted': len(g.votes), 'total': len(self.items)} for g in self.guests.values()],
                'results': self.results() if self.revealed else None}

    def host_view(self):
        with self.lock:
            return {**self._common(), 'code': self.code}

    def guest_view(self, token):
        with self.lock:
            guest = self.guest(token)
            return {**self._common(), 'you': {'id': guest.id, 'name': guest.name, 'votes': dict(guest.votes)}}


class CouchManager:
    """Starts and stops the guest server around a CouchSession. Used by the loopback host server."""

    def __init__(self, host=None, port=8770):
        self.host = check_host(host) if host else None
        self.port = port
        self.session, self.server, self.url = None, None, None
        self.lock = threading.Lock()

    def start(self, shortlist):
        with self.lock:
            self._stop()
            session = CouchSession(shortlist)
            host = self.host or lan_address()
            try:
                server = make_guest_server(session, host, self.port)
            except OSError as exc:
                raise CouchError(f'Could not listen on {host}:{self.port} ({exc.strerror or exc})') from None
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.session, self.server = session, server
            self.url = f'http://{host}:{server.server_port}/join'
            return self.view()

    def stop(self):
        with self.lock:
            self._stop()

    def _stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.session, self.server, self.url = None, None, None

    def active(self):
        with self.lock:
            if self.session and self.session.expired():
                self._stop()
            return self.session

    def view(self):
        session = self.session
        if not session:
            return {'active': False}
        return {**session.host_view(), 'url': self.url, 'join_url': f'{self.url}#{session.code}'}

    def qr_svg(self):
        session = self.active()
        if not session:
            raise CouchError('No couch session is running')
        return qr.svg(f'{self.url}#{session.code}')


def make_guest_server(session, host, port):
    """Network-facing server for guests. Exposes nothing but the couch routes below."""
    host = check_host(host)
    pages = {'/join': ('couch.html', 'text/html; charset=utf-8'),
             '/couch.js': ('couch.js', 'text/javascript; charset=utf-8'),
             '/style.css': ('style.css', 'text/css; charset=utf-8')}

    class GuestHandler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def respond(self, status, value, content_type='application/json'):
            body = json.dumps(value, allow_nan=False).encode() if content_type == 'application/json' else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            # The Host check defeats DNS rebinding; the Origin check refuses other sites' pages.
            expected = f'{host}:{self.server.server_port}'
            if self.headers.get('Host') != expected:
                self.respond(403, {'error': 'Use the address shown on the TV'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin != f'http://{expected}':
                self.respond(403, {'error': 'Cross-origin requests are not allowed'})
                return False
            if session.expired():
                self.respond(410, {'error': 'This couch session has ended'})
                return False
            return True

        def token(self):
            return self.headers.get('X-Flicks-Guest', '')

        def do_GET(self):
            if not self.allowed():
                return
            path = self.path.split('?', 1)[0]
            try:
                if path == '/api/couch/state':
                    self.respond(200, session.guest_view(self.token()))
                elif path in pages:
                    name, mime = pages[path]
                    self.respond(200, (STATIC/name).read_bytes(), mime)
                else:
                    self.respond(404, {'error': 'Not found'})
            except CouchAuthError as error:
                self.respond(401, {'error': str(error)})

        def do_POST(self):
            if not self.allowed():
                return
            try:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise CouchError('Expected application/json')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    raise CouchError('Request must contain 1–1024 bytes')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise CouchError('Expected a JSON object')
                if self.path == '/api/couch/join':
                    if set(data) != {'code', 'name'}:
                        raise CouchError('Expected code and name')
                    token, guest = session.join(data['code'], data['name'])
                    self.respond(200, {'token': token, 'name': guest.name})
                elif self.path == '/api/couch/vote':
                    if set(data) != {'id', 'value'}:
                        raise CouchError('Expected id and value')
                    session.vote(self.token(), data['id'], data['value'])
                    self.respond(200, session.guest_view(self.token()))
                elif self.path == '/api/couch/remote':
                    if set(data) - {'action', 'id'} or 'action' not in data:
                        raise CouchError('Expected action and optional id')
                    session.remote(self.token(), data['action'], data.get('id'))
                    self.respond(200, session.guest_view(self.token()))
                else:
                    self.respond(404, {'error': 'Not found'})
            except CouchAuthError as error:
                self.respond(401, {'error': str(error)})
            except (CouchError, ValueError, TypeError) as error:
                self.respond(400, {'error': str(error)})

    return ThreadingHTTPServer((host, port), GuestHandler)
