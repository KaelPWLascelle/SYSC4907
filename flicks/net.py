"""Outbound HTTP for explicit, user-requested actions (poster fetch, dataset, podcast and archive
import, and playing or downloading remote media).

Browsing, rating and asking never make remote requests (docs/adr/0001-local-first.md); only these
actions do, and they send public catalogue data only (docs/adr/0010-podcasts.md,
docs/adr/0011-streaming.md).
"""
import functools
import ipaddress
import json
from pathlib import Path
import ssl
from urllib import parse, request

USER_AGENT = 'Flicks (SYSC 4907 student project; https://github.com/KaelPWLascelle/SYSC4907)'
CHUNK = 256 * 1024
WEB_SCHEMES = frozenset({'http', 'https'})


@functools.cache
def ssl_context():
    """Verified TLS. python.org's macOS Python has no CA bundle until its Install Certificates step,
    so fall back to the operating system's bundle rather than ever skipping verification."""
    context = ssl.create_default_context()
    if not context.get_ca_certs() and Path('/etc/ssl/cert.pem').is_file():
        context.load_verify_locations('/etc/ssl/cert.pem')
    return context


def get(url, limit, *, accept='*/*', timeout=30):
    """The response body, refusing anything larger than `limit` bytes."""
    req = request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept})
    with request.urlopen(req, timeout=timeout, context=ssl_context()) as reply:
        data = reply.read(limit + 1)
    if len(data) > limit:
        raise ValueError('response too large')
    return data


def get_json(url, params, limit=4 * 1024 * 1024, **kwargs):
    return json.loads(get(f'{url}?{parse.urlencode(params)}', limit, accept='application/json', **kwargs))


def public_web(url):
    """True for an http(s) URL that does not name this machine or a private network.

    Remote media comes from feeds and archives we do not control; a feed must not be able to make
    Flicks fetch from the router, a printer or itself. Host names are not resolved, so this stops
    literal addresses and local names, not a public name that resolves to a private address.
    """
    parts = parse.urlsplit(url)
    host = (parts.hostname or '').lower()
    if parts.scheme not in WEB_SCHEMES or not host:
        return False
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.home.arpa')):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return '.' in host  # a bare name ("router") is a local name
    return address.is_global


def _require_public(url):
    if not public_web(url):
        raise ValueError('only public http(s) addresses may be fetched')


class _PublicWebRedirects(request.HTTPRedirectHandler):
    """Podcast and archive links pass through several redirects; none may leave the public web."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, headers, *, method='GET', timeout):
    _require_public(url)
    opener = request.build_opener(request.HTTPSHandler(context=ssl_context()), _PublicWebRedirects)
    return opener.open(request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*', **headers},
                                       method=method), timeout=timeout)


def open_stream(url, headers=None, *, method='GET', timeout=30):
    """An open response for relaying remote media; the caller reads and closes it. Raises HTTPError for 4xx/5xx."""
    return _open(url, headers or {}, method=method, timeout=timeout)


def download(url, path: Path, limit, *, progress=None, timeout=60):
    """Stream the body to `path`, refusing more than `limit` bytes; returns the number of bytes.

    `progress(received, total)` is called after each chunk; total is None when the server does not say.
    """
    with _open(url, {}, timeout=timeout) as reply, Path(path).open('wb') as out:
        total = int(reply.headers.get('Content-Length') or 0) or None
        if total and total > limit:
            raise ValueError('file too large')
        received = 0
        while chunk := reply.read(CHUNK):
            received += len(chunk)
            if received > limit:
                raise ValueError('file too large')
            out.write(chunk)
            if progress:
                progress(received, total)
    return received
