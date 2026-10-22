"""Outbound HTTP for explicit, user-requested actions (poster fetch, dataset, trailer and archive
import, and playing remote media).

Browsing, rating and asking never make remote requests (docs/adr/0001-local-first.md); only these
actions do, and they send public catalogue data only (docs/adr/0011-streaming.md).
"""
import functools
from http.client import IncompleteRead
import ipaddress
import json
from pathlib import Path
import ssl
import time
from urllib import error, parse, request

USER_AGENT = 'Flicks (SYSC 4907 student project; https://github.com/KaelPWLascelle/SYSC4907)'
CHUNK = 256 * 1024
WEB_SCHEMES = frozenset({'http', 'https'})
# Waits before retrying a request that failed for a temporary reason (a timeout, a dropped connection,
# HTTP 429 or 5xx): a long import should not fail on one blip from Wikipedia or TVmaze.
RETRY_WAITS = (2, 6, 15)


@functools.cache
def ssl_context():
    """Verified TLS. python.org's macOS Python has no CA bundle until its Install Certificates step,
    so fall back to the operating system's bundle rather than ever skipping verification."""
    context = ssl.create_default_context()
    if not context.get_ca_certs() and Path('/etc/ssl/cert.pem').is_file():
        context.load_verify_locations('/etc/ssl/cert.pem')
    return context


def get(url, limit, *, accept='*/*', timeout=30, waits=RETRY_WAITS):
    """The response body, refusing anything larger than `limit` bytes. Temporary failures are retried."""
    req = request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept})
    for wait in (*waits, None):
        try:
            with request.urlopen(req, timeout=timeout, context=ssl_context()) as reply:
                data = reply.read(limit + 1)
            break
        except error.HTTPError as failure:
            if wait is None or not (failure.code == 429 or failure.code >= 500):
                raise
        except (error.URLError, TimeoutError, ConnectionError, IncompleteRead):  # IncompleteRead: dropped mid-body
            if wait is None:
                raise
        time.sleep(wait)
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
    """Archive links pass through several redirects; none may leave the public web."""

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
