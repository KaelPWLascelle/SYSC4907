"""Remote media played through Flicks: the browser only ever talks to this machine (docs/adr/0011-streaming.md).

When a film's media lives elsewhere (a public-domain copy on the Internet Archive), pressing Play
makes the host app fetch it and pass it on, chunk by chunk, with the browser's Range header so seeking
works. The URL comes from an imported index, never from the request; the response is always labelled
with the expected video type, whatever the remote server claims; and the first bytes of a file must
look like video.
"""
from dataclasses import dataclass
import re
from urllib import error

from . import net

CHUNK = 256 * 1024
# Bytes needed to recognise a container (an MP4 box type sits at bytes 4-8). Smaller responses, such as
# Safari's "bytes=0-1" probe before it plays anything, cannot be judged and are passed on as they are:
# they are still labelled as video with nosniff, so they cannot become a page.
SNIFF_BYTES = 8
# One range, as browsers send for media: "bytes=0-", "bytes=1000-1999" or "bytes=-500".
RANGE = re.compile(r'bytes=(\d+-\d*|-\d+)')
PASSED_HEADERS = ('Content-Length', 'Content-Range')


def sniff_video(head: bytes):
    """'.mp4' for an MP4/QuickTime box, '.webm' for Matroska/WebM, or None. Never trust the server's type."""
    if head[4:8] in (b'ftyp', b'moov', b'mdat', b'free', b'wide', b'skip'):
        return '.mp4'
    if head[:4] == b'\x1a\x45\xdf\xa3':
        return '.webm'
    return None


@dataclass(frozen=True)
class Remote:
    """Where a title's media lives, and how to present it."""
    url: str
    media_type: str     # always sent to the browser, whatever the remote server says
    source: str         # shown to the user, e.g. "Internet Archive"
    page: str = ''      # attribution link; empty when there is none


class RelayError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass
class Relayed:
    status: int
    headers: dict
    chunks: object      # an iterator of bytes that closes the remote response when it ends


class Streams:
    """{content ID: Remote} for every title that can be played from elsewhere. `opener` is swappable for tests."""

    def __init__(self, remotes=None, opener=net.open_stream):
        self.remotes = dict(remotes or {})
        self.opener = opener

    def get(self, content_id):
        return self.remotes.get(content_id)

    def items(self):
        return self.remotes.items()

    def __len__(self):
        return len(self.remotes)

    def open(self, content_id, range_header=None, method='GET'):
        remote = self.remotes.get(content_id)
        if remote is None:
            raise RelayError(404, 'This title has no playable file')
        return relay(remote, range_header, method, self.opener)


def relay(remote: Remote, range_header=None, method='GET', opener=net.open_stream) -> Relayed:
    headers = {}
    wanted = (range_header or '').strip()
    if RANGE.fullmatch(wanted):
        headers['Range'] = wanted  # anything else (several ranges, garbage) is dropped: the whole file is sent
    try:
        reply = opener(remote.url, headers, method=method)
    except error.HTTPError as exc:
        if exc.code == 416:
            raise RelayError(416, 'That part of the file does not exist') from None
        raise RelayError(502, f'{remote.source} answered {exc.code}') from None
    except (OSError, ValueError, error.URLError):
        raise RelayError(502, f'Could not reach {remote.source}. Check your internet connection.') from None
    if reply.status not in (200, 206):
        reply.close()
        raise RelayError(502, f'{remote.source} answered {reply.status}')
    out = {'Content-Type': remote.media_type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store'}
    out.update({name: reply.headers[name] for name in PASSED_HEADERS if reply.headers.get(name)})
    if method == 'HEAD':
        reply.close()
        return Relayed(reply.status, out, iter(()))
    first = reply.read(CHUNK)
    from_start = reply.status == 200 or (reply.headers.get('Content-Range') or '').startswith('bytes 0-')
    if from_start and len(first) >= SNIFF_BYTES and sniff_video(first[:16]) is None:
        reply.close()
        raise RelayError(502, f'{remote.source} did not send video Flicks can play')

    def chunks():
        try:
            if first:
                yield first
            while chunk := reply.read(CHUNK):
                yield chunk
        finally:
            reply.close()

    return Relayed(reply.status, out, chunks())
