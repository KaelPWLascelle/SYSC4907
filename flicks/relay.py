"""Remote media played through Flicks: the browser only ever talks to this machine (docs/adr/0011-streaming.md).

When a title's media lives elsewhere (a podcast episode on its publisher's server, a public-domain
film on the Internet Archive), pressing Play makes the host app fetch it and pass it on, chunk by
chunk, with the browser's Range header so seeking works. The URL comes from an imported index,
never from the request; the response is always labelled with the expected audio or video type,
whatever the remote server claims; and the first bytes of a file must look like audio or video.
"""
from dataclasses import dataclass
import re
from urllib import error

from . import net

CHUNK = 256 * 1024
# One range, as browsers send for media: "bytes=0-", "bytes=1000-1999" or "bytes=-500".
RANGE = re.compile(r'bytes=(\d+-\d*|-\d+)')
PASSED_HEADERS = ('Content-Length', 'Content-Range')


def sniff_audio(head: bytes):
    """File extension from the first bytes, or None. Never trust the server's content type."""
    if head[:3] == b'ID3':
        return '.mp3'
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        # MPEG frame sync: layer bits 00 mean AAC in an ADTS stream, anything else is MP3.
        return '.aac' if (head[1] >> 1) & 0b11 == 0 else '.mp3'
    if head[4:8] == b'ftyp':
        return '.m4a'
    if head[:4] == b'OggS':
        return '.ogg'
    return None


def sniff_video(head: bytes):
    """'.mp4' for an MP4/QuickTime box, '.webm' for Matroska/WebM, or None."""
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
    audio: bool
    source: str         # shown to the user: the show's name, or "Internet Archive"
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
    if from_start and first and (sniff_audio if remote.audio else sniff_video)(first[:16]) is None:
        reply.close()
        kind = 'audio' if remote.audio else 'video'
        raise RelayError(502, f'{remote.source} did not send {kind} Flicks can play')

    def chunks():
        try:
            if first:
                yield first
            while chunk := reply.read(CHUNK):
                yield chunk
        finally:
            reply.close()

    return Relayed(reply.status, out, chunks())
