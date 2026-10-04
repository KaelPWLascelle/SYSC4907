"""Request guard shared by the host and couch guest apps.

A pure ASGI middleware (not BaseHTTPMiddleware) so it can buffer and cap request bodies before any
route sees them, and add headers to streamed responses such as video without touching their bodies.
"""
from dataclasses import dataclass, field
import json

from starlette.datastructures import Headers

CSP = ("default-src 'self'; img-src 'self' blob:; media-src 'self'; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
BODY_METHODS = frozenset({'POST', 'PUT', 'PATCH'})


@dataclass(frozen=True)
class RawBody:
    """A route that takes a non-JSON body (e.g. an audio upload)."""
    types: frozenset
    limit: int
    error: str = 'Unsupported content type'


@dataclass(frozen=True)
class GuardPolicy:
    hosts: frozenset                       # Host header names (without port) this app answers to
    origins: frozenset                     # exact Origin values allowed to call it
    json_limit: int = 8192
    raw_bodies: dict = field(default_factory=dict)   # path -> RawBody
    long_cache_prefixes: tuple = ('/assets/',)       # fingerprinted build output


def hostname(host_header):
    """'127.0.0.1:8765' -> '127.0.0.1'. IPv6 literals keep their brackets; we only allow IPv4 and localhost."""
    if host_header.startswith('['):
        return host_header.split(']')[0] + ']'
    return host_header.rsplit(':', 1)[0] if host_header.count(':') == 1 else host_header


class RequestGuard:
    def __init__(self, app, policy: GuardPolicy):
        self.app, self.policy = app, policy

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if hostname(headers.get('host', '')) not in self.policy.hosts:  # DNS rebinding
            await _error(send, 403, 'Use the address this app was opened on')
            return
        origin = headers.get('origin')
        if origin is not None and origin not in self.policy.origins:    # other sites' pages
            await _error(send, 403, 'Cross-origin requests are not allowed')
            return
        method, path = scope['method'], scope['path']
        if method in BODY_METHODS:
            raw = self.policy.raw_bodies.get(path)
            content_type = headers.get('content-type', '').split(';')[0].strip().lower()
            # JSON-only bodies force a CORS preflight for cross-site POSTs, which we never approve.
            allowed, limit = (raw.types, raw.limit) if raw else (frozenset({'application/json'}), self.policy.json_limit)
            if content_type not in allowed:
                await _error(send, 415, raw.error if raw else 'Expected application/json')
                return
            declared = headers.get('content-length')
            if declared is not None and (not declared.isdigit() or int(declared) > limit):
                await _error(send, 413, f'Request body must be at most {limit} bytes')
                return
            body = await _read_body(receive, limit)
            if body is None:
                await _error(send, 413, f'Request body must be at most {limit} bytes')
                return
            receive = _replay(body, receive)
        await self.app(scope, receive, self._with_headers(send, path))

    def _with_headers(self, send, path):
        long_cache = path.startswith(self.policy.long_cache_prefixes)

        async def wrapped(message):
            if message['type'] == 'http.response.start':
                headers = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'cache-control' or not long_cache]
                names = {k.lower() for k, _ in headers}
                headers += [(b'x-content-type-options', b'nosniff'), (b'referrer-policy', b'no-referrer'),
                            (b'content-security-policy', CSP.encode())]
                if long_cache:
                    headers.append((b'cache-control', b'public, max-age=31536000, immutable'))
                elif b'cache-control' not in names:
                    headers.append((b'cache-control', b'no-store'))
                message = {**message, 'headers': headers}
            await send(message)
        return wrapped


async def _read_body(receive, limit):
    """The whole body, or None once it exceeds limit (covers chunked uploads with no Content-Length)."""
    chunks, size = [], 0
    while True:
        message = await receive()
        if message['type'] == 'http.disconnect':
            return b''.join(chunks)
        chunk = message.get('body', b'')
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
        if not message.get('more_body', False):
            return b''.join(chunks)


def _replay(body, original):
    """Hand the buffered body to the app once, then defer to the real channel so disconnects still arrive."""
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return await original()
        sent = True
        return {'type': 'http.request', 'body': body, 'more_body': False}
    return receive


async def _error(send, status, message):
    body = json.dumps({'error': message}).encode()
    await send({'type': 'http.response.start', 'status': status,
                'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode()),
                            (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'),
                            (b'content-security-policy', CSP.encode())]})
    await send({'type': 'http.response.body', 'body': body})
