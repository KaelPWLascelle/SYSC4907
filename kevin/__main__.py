"""Loopback-only demo server; run with python -m kevin."""
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
from .core import load_catalog, Recommender, Session
from .store import FeedbackStore

ROOT = Path(__file__).parent


def make_server(catalog_path, db_path, port=8765):
    catalog = load_catalog(catalog_path)
    engine, store = Recommender(catalog), FeedbackStore(db_path)
    ids = {item.id for item in catalog}

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
                    self.respond(200, dict(catalog=[asdict(i) for i in catalog], feedback=store.all()))
                except sqlite3.Error:
                    self.respond(503, {'error': 'Local storage is unavailable; check the database path'})
            elif path in ('/', '/app.js', '/style.css'):
                name, mime = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}[path]
                self.respond(200, (ROOT/'static'/name).read_bytes(), mime)
            else:
                self.respond(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.allowed():
                return
            try:
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
                elif self.path == '/api/recommend':
                    if set(data) - {'session', 'mode'}:
                        raise ValueError('Unknown request fields')
                    session = Session(**data.get('session', {}))
                    feedback = store.all()
                    self.respond(200, {'recommendations': engine.recommend(feedback, session, data.get('mode', 'session')),
                                       'cold_start': not any(k in ids and v == 1 for k, v in feedback.items())})
                else:
                    self.respond(404, {'error': 'Not found'})
            except (ValueError, TypeError, KeyError) as error:
                self.respond(400, {'error': str(error)})
            except sqlite3.Error:
                self.respond(503, {'error': 'Local storage is unavailable; retry or check the database path'})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description='Kevin local recommendation demo')
    parser.add_argument('--catalog', type=Path, default=ROOT/'data'/'movies.json')
    parser.add_argument('--db', type=Path, default=Path.home()/'.kevin'/'feedback.sqlite3')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = make_server(args.catalog, args.db, args.port)
    print(f'Kevin: http://127.0.0.1:{server.server_port} — feedback: {args.db}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
