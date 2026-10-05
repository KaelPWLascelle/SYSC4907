"""Outbound HTTP for explicit, user-run commands (poster fetch, dataset import).

The app itself never makes remote requests (docs/adr/0001-local-first.md); only these one-time
commands do, and they send public catalogue data only.
"""
import functools
import json
from pathlib import Path
import ssl
from urllib import parse, request

USER_AGENT = 'Flicks (SYSC 4907 student project; https://github.com/KaelPWLascelle/SYSC4907)'


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
