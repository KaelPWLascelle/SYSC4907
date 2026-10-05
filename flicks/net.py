"""Outbound HTTP for explicit, user-requested actions (poster fetch, dataset and podcast import,
episode downloads).

Browsing, rating and asking never make remote requests (docs/adr/0001-local-first.md); only these
actions do, and they send public catalogue data only (docs/adr/0010-podcasts.md).
"""
import functools
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


class _WebOnlyRedirects(request.HTTPRedirectHandler):
    """Podcast links pass through several tracking redirects; none may leave http(s) (e.g. for ftp:)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if parse.urlsplit(newurl).scheme not in WEB_SCHEMES:
            raise ValueError('redirected away from http(s)')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, path: Path, limit, *, progress=None, timeout=60):
    """Stream the body to `path`, refusing more than `limit` bytes; returns the number of bytes.

    `progress(received, total)` is called after each chunk; total is None when the server does not say.
    """
    if parse.urlsplit(url).scheme not in WEB_SCHEMES:
        raise ValueError('only http(s) downloads are allowed')
    opener = request.build_opener(request.HTTPSHandler(context=ssl_context()), _WebOnlyRedirects)
    req = request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
    with opener.open(req, timeout=timeout) as reply, Path(path).open('wb') as out:
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
