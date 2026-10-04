"""Couch-mode guest server: the only thing Flicks exposes on the home network (docs/couch.md).

It is a separate app on its own port that exists only while a session runs. It has no host routes
(ratings, history, voice, commands), so they cannot be reached from the network at all.
"""
from pathlib import Path
import threading

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import StrictInt, StrictStr

from .. import qr
from ..couch import CouchAuthError, CouchError, CouchSession, check_host, lan_address
from . import errors
from .schemas import Body, PlayerIn
from .security import GuardPolicy, RequestGuard
from .server import ServerThread

GUEST_JSON_LIMIT = 1024


class JoinIn(Body):
    code: StrictStr
    name: StrictStr


class VoteIn(Body):
    id: StrictStr
    value: StrictInt


def create_guest_app(session: CouchSession, host: str, port: int, posters=None, static_dir: Path | None = None):
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.add_middleware(RequestGuard, policy=GuardPolicy(hosts=frozenset({host}), origins=frozenset({f'http://{host}:{port}'}),
                                                        json_limit=GUEST_JSON_LIMIT))
    errors.install(app)

    @app.exception_handler(CouchAuthError)
    async def unauthorized(_request: Request, error: CouchAuthError):
        return JSONResponse({'error': str(error)}, 401)

    @app.exception_handler(CouchError)
    async def bad_request(_request: Request, error: CouchError):
        return JSONResponse({'error': str(error)}, 400)

    def live():
        if session.expired():
            raise HTTPException(410, 'This couch session has ended')
        return session

    def guest_token(x_flicks_guest: str = Header(default='')):
        return x_flicks_guest

    @app.get('/join')
    def join_page(_s=Depends(live)):
        page = static_dir/'couch.html' if static_dir else None
        if not page or not page.is_file():
            raise HTTPException(503, 'The couch page is not built; run `npm --prefix web run build`')
        return FileResponse(page, media_type='text/html; charset=utf-8')

    @app.get('/posters/{content_id}')
    def poster(content_id: str, s=Depends(live)):
        image = posters.read(content_id) if posters and content_id in s.order else None  # shortlist only
        if image is None:
            raise HTTPException(404, 'Not found')
        return Response(image[0], media_type=image[1], headers={'Cache-Control': 'private, max-age=3600'})

    @app.get('/api/couch/state')
    def state(s=Depends(live), token=Depends(guest_token)):
        return s.guest_view(token)

    @app.post('/api/couch/join')
    def join(body: JoinIn, s=Depends(live)):
        token, guest = s.join(body.code, body.name)
        return {'token': token, 'name': guest.name}

    @app.post('/api/couch/vote')
    def vote(body: VoteIn, s=Depends(live), token=Depends(guest_token)):
        s.vote(token, body.id, body.value)
        return s.guest_view(token)

    @app.post('/api/couch/remote')
    def remote(body: PlayerIn, s=Depends(live), token=Depends(guest_token)):
        s.remote(token, body.action, body.id)
        return s.guest_view(token)

    if static_dir and (static_dir/'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=static_dir/'assets'), name='assets')
    return app


class CouchManager:
    """Starts and stops the guest server around a CouchSession. Owned by the host app."""

    def __init__(self, host=None, port=8770, posters=None, static_dir=None):
        self.host = check_host(host) if host else None
        self.port, self.posters, self.static_dir = port, posters, static_dir
        self.session, self.server, self.url = None, None, None
        self.lock = threading.Lock()

    def start(self, shortlist):
        with self.lock:
            self._stop()
            session = CouchSession(shortlist, posters=set(self.posters.ids()) if self.posters else ())
            host = self.host or lan_address()
            try:
                server = ServerThread(lambda port: create_guest_app(session, host, port, self.posters, self.static_dir),
                                      host, self.port).start()
            except (OSError, RuntimeError) as error:
                raise CouchError(f'Could not listen on {host}:{self.port} ({getattr(error, "strerror", None) or error})') from None
            self.session, self.server = session, server
            self.url = f'http://{host}:{server.port}/join'
            return self._view()

    def stop(self):
        with self.lock:
            self._stop()

    def _stop(self):
        if self.server:
            self.server.stop()
        self.session, self.server, self.url = None, None, None

    def active(self):
        """The running session, closing it first if it has expired."""
        with self.lock:
            if self.session and self.session.expired():
                self._stop()
            return self.session

    def view(self):
        with self.lock:
            return self._view()

    def _view(self):
        if not self.session:
            return {'active': False}
        return {**self.session.host_view(), 'url': self.url, 'join_url': f'{self.url}#{self.session.code}'}

    def qr_svg(self):
        with self.lock:
            if not self.session:
                raise CouchError('No couch session is running')
            return qr.svg(f'{self.url}#{self.session.code}')
