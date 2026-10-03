"""Loopback-only demo server; run with python -m kevin. Couch-mode guests use kevin.couch's separate LAN server."""
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
from .core import load_catalog, Recommender, Session
from .store import FeedbackStore
from .commands import CommandInterpreter
from .couch import CouchManager
from .voice import AUDIO_TYPES, MAX_AUDIO_BYTES, LocalWhisper, VoiceBusy, VoiceUnavailable
from .intent import SystemOneInterpreter
from .systemone import DecisionClient, HttpBackend, LexicalBackend
from .tagging import TaggedDecision, load_tags

ROOT = Path(__file__).parent


def make_server(catalog_path, db_path, port=8765, voice=None, tags_path=None, system_one=None, couch=None):
    catalog = load_catalog(catalog_path)
    decision = TaggedDecision(load_tags(tags_path, catalog)) if tags_path else None
    engine, store = Recommender(catalog, decision=decision), FeedbackStore(db_path)
    ids = {item.id for item in catalog}
    # system_one: a DecisionClient whose backend must be local (SystemOneInterpreter enforces it).
    interpreter = SystemOneInterpreter(catalog, system_one) if system_one else CommandInterpreter(catalog)
    speech = voice if voice is not None else LocalWhisper()
    # couch: a CouchManager when started with --couch. Guests reach its own LAN server, never this one.

    class Handler(BaseHTTPRequestHandler):
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
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            hosts = {expected, f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in hosts:
                self.respond(403, {'error': 'Use the local Kevin address'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://{host}' for host in hosts}:
                self.respond(403, {'error': 'Cross-origin requests are not allowed'})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            path = urlsplit(self.path).path
            if path == '/api/state':
                try:
                    self.respond(200, dict(catalog=[asdict(i) for i in catalog], feedback=store.all(), voice=speech.status(),
                                           assistant=interpreter.name, tagged=decision is not None, couch=couch is not None))
                except sqlite3.Error:
                    self.respond(503, {'error': 'Local storage is unavailable; check the database path'})
            elif couch and path == '/api/couch':
                self.respond(200, couch.view() if couch.active() else {'active': False})
            elif couch and path == '/api/couch/qr.svg':
                try:
                    self.respond(200, couch.qr_svg().encode(), 'image/svg+xml')
                except ValueError as error:
                    self.respond(404, {'error': str(error)})
            elif path in ('/', '/app.js', '/voice.js', '/couch-host.js', '/style.css'):
                name, mime = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/voice.js': ('voice.js', 'text/javascript; charset=utf-8'), '/couch-host.js': ('couch-host.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}[path]
                self.respond(200, (ROOT/'static'/name).read_bytes(), mime)
            else:
                self.respond(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.allowed():
                return
            try:
                if self.path == '/api/transcribe':
                    if self.headers.get('Content-Type', '').split(';')[0] not in AUDIO_TYPES:
                        raise ValueError('Expected an audio recording')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= MAX_AUDIO_BYTES:
                        raise ValueError('Audio must contain 1 byte to 5 MiB')
                    result = speech.transcribe(self.rfile.read(length))
                    self.respond(200, result)
                    return
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Expected application/json')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 8192:
                    raise ValueError('Request must contain 1–8192 bytes')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected a JSON object')
                if self.path == '/api/feedback':
                    if set(data) != {'id', 'value'} or not isinstance(data['id'], str) or data['id'] not in ids:
                        raise ValueError('Unknown content ID or feedback fields')
                    store.set(data['id'], data['value'])
                    self.respond(200, {'feedback': store.all()})
                elif self.path in ('/api/command/preview', '/api/command/apply'):
                    if set(data) - {'text', 'session'} or 'text' not in data:
                        raise ValueError('Expected command text and optional session')
                    session = Session(**data.get('session', {}))
                    command = interpreter.parse(data['text'])
                    if self.path.endswith('/apply'):
                        if command['intent'] == 'unknown':
                            raise ValueError(command['summary'])
                        if command['intent'] == 'feedback':
                            store.set(command['id'], command['value'])
                        else:
                            session = Session(**{**asdict(session), **command['patch']})
                    self.respond(200, {'command': command, 'session': asdict(session), 'feedback': store.all()})
                elif self.path == '/api/recommend':
                    if set(data) - {'session', 'mode'}:
                        raise ValueError('Unknown request fields')
                    session = Session(**data.get('session', {}))
                    feedback = store.all()
                    self.respond(200, {'recommendations': engine.recommend(feedback, session, data.get('mode', 'session')),
                                       'cold_start': not any(k in ids and v == 1 for k, v in feedback.items())})
                elif couch and self.path == '/api/couch/start':
                    if set(data) - {'session'}:
                        raise ValueError('Unknown request fields')
                    shortlist = engine.recommend(store.all(), Session(**data.get('session', {})), 'session', limit=8)
                    self.respond(200, couch.start(shortlist))
                elif couch and self.path in ('/api/couch/stop', '/api/couch/reveal', '/api/couch/player'):
                    live = couch.active()
                    if self.path.endswith('/stop'):
                        couch.stop()
                    elif not live:
                        raise ValueError('No couch session is running')
                    elif self.path.endswith('/reveal'):
                        live.reveal()
                    else:
                        if set(data) - {'action', 'id'} or 'action' not in data:
                            raise ValueError('Expected action and optional id')
                        live.control(data['action'], data.get('id'))
                    self.respond(200, couch.view())
                else:
                    self.respond(404, {'error': 'Not found'})
            except (ValueError, TypeError, KeyError) as error:
                self.respond(400, {'error': str(error)})
            except sqlite3.Error:
                self.respond(503, {'error': 'Local storage is unavailable; retry or check the database path'})
            except VoiceUnavailable as error:
                self.respond(503, {'error': str(error)})
            except VoiceBusy as error:
                self.respond(409, {'error': str(error)})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description='Kevin local recommendation demo')
    parser.add_argument('--catalog', type=Path, default=ROOT/'data'/'movies.json')
    parser.add_argument('--db', type=Path, default=Path.home()/'.kevin'/'feedback.sqlite3')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--voice-model', type=Path, help='Local faster-whisper model directory; no runtime downloads')
    parser.add_argument('--tags', type=Path, help='System One tag file from python -m kevin.tagging (soft mood/intensity)')
    parser.add_argument('--couch', action='store_true', help='Allow couch sessions: phones on your Wi-Fi join by QR code to vote and use a remote')
    parser.add_argument('--couch-host', help='Home-network address guests connect to (default: detected)')
    parser.add_argument('--couch-port', type=int, default=8770, help='Port for the guest server while a couch session runs')
    parser.add_argument('--system-one-url', help='Local System One server for free-text commands, e.g. http://127.0.0.1:8000 (laya-serve), or "lexical" for the offline stand-in')
    args = parser.parse_args()
    if args.system_one_url == 'lexical':  # offline demo of the fallback path; not a model
        system_one = DecisionClient(LexicalBackend())
    else:
        system_one = DecisionClient(HttpBackend(args.system_one_url, timeout=5)) if args.system_one_url else None
    couch = CouchManager(args.couch_host, args.couch_port) if args.couch else None
    server = make_server(args.catalog, args.db, args.port, LocalWhisper(args.voice_model), args.tags, system_one, couch)
    print(f'Kevin: http://127.0.0.1:{server.server_port} — feedback: {args.db}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if couch:
            couch.stop()
        server.server_close()

if __name__ == '__main__':
    main()
