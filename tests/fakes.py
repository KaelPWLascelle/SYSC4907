"""A stand-in for net.open_stream: an upstream media server that honours Range requests, offline."""
from email.message import Message
import re
from urllib import error


class Reply:
    def __init__(self, status, headers, body):
        self.status, self.body, self.closed = status, body, False
        self.headers = Message()
        for name, value in headers.items():
            self.headers[name] = value

    def read(self, size=-1):
        chunk, self.body = (self.body, b'') if size < 0 else (self.body[:size], self.body[size:])
        return chunk

    def close(self):
        self.closed = True


class Upstream:
    """Serves `body` like a CDN: 200 for the whole file, 206 with Content-Range for one range."""

    def __init__(self, body, status=None, error_code=None, content_type='text/html'):
        self.body, self.status, self.error_code, self.content_type = body, status, error_code, content_type
        self.calls, self.replies = [], []

    def __call__(self, url, headers=None, method='GET'):
        self.calls.append((url, dict(headers or {}), method))
        if self.error_code:
            raise error.HTTPError(url, self.error_code, 'error', {}, None)
        wanted = re.fullmatch(r'bytes=(\d+)-(\d*)', (headers or {}).get('Range', ''))
        size = len(self.body)
        if wanted:
            start, end = int(wanted[1]), int(wanted[2] or size - 1)
            reply = Reply(self.status or 206, {'Content-Type': self.content_type, 'Content-Length': str(end - start + 1),
                                               'Content-Range': f'bytes {start}-{end}/{size}'}, self.body[start:end + 1])
        else:
            reply = Reply(self.status or 200, {'Content-Type': self.content_type, 'Content-Length': str(size)}, self.body)
        self.replies.append(reply)
        return reply
