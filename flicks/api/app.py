"""The host app: the loopback-only API plus the built interface (docs/adr/0002-fastapi-backend.md)."""
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings
from ..services import Services
from ..voice import AUDIO_TYPES, MAX_AUDIO_BYTES
from . import errors
from .routes import assistant, couch, library, playback
from .security import GuardPolicy, RawBody, RequestGuard

HOSTS = frozenset({'127.0.0.1', 'localhost'})
# Top-level files the frontend build may emit next to index.html (Vite copies web/public/ here).
PUBLIC_FILES = {'manifest.webmanifest': 'application/manifest+json', 'favicon.svg': 'image/svg+xml',
                'icon-192.png': 'image/png', 'icon-512.png': 'image/png', 'apple-touch-icon.png': 'image/png'}
NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Flicks</title>
<h1>The Flicks frontend is not built yet</h1>
<p>From the repository root run <code>npm --prefix web ci</code> and <code>npm --prefix web run build</code>, then reload.</p>"""


def create_app(settings: Settings, services: Services) -> FastAPI:
    app = FastAPI(title='Flicks', openapi_url=None, docs_url=None, redoc_url=None)
    app.state.services = services
    app.add_middleware(RequestGuard, policy=GuardPolicy(
        hosts=HOSTS, origins=settings.origins,
        raw_bodies={'/api/transcribe': RawBody(frozenset(AUDIO_TYPES), MAX_AUDIO_BYTES, 'Expected an audio recording')}))
    errors.install(app)

    for router in (library.router, assistant.router, playback.router):
        app.include_router(router)
    if services.couch is not None:  # absent unless started with --couch: the routes simply do not exist
        app.include_router(couch.router)

    static = settings.static_dir

    @app.get('/', include_in_schema=False)
    def index():
        page = static/'index.html'
        return FileResponse(page, media_type='text/html; charset=utf-8') if page.is_file() else HTMLResponse(NOT_BUILT, 503)

    @app.get('/{name}', include_in_schema=False)
    def public_file(name: str):
        if name not in PUBLIC_FILES or not (static/name).is_file():
            raise HTTPException(404, 'Not found')
        return FileResponse(static/name, media_type=PUBLIC_FILES[name])

    if (static/'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=static/'assets'), name='assets')
    return app
