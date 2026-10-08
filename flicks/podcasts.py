"""Podcast episodes at runtime: where each one's audio is, which are downloaded, and downloads in progress.

Pressing Play streams an episode from its publisher through Flicks (flicks/relay.py); pressing
Download keeps a copy for offline listening. Either way the host app fetches the URL in the imported
feed (never a URL from a request) and checks that it is audio. Nothing about the user is sent beyond
the request itself (docs/adr/0010-podcasts.md, docs/adr/0011-streaming.md).
"""
from dataclasses import dataclass
import json
from pathlib import Path
import queue
import threading
from urllib import error, parse

from . import net
from .media import MediaFile
from .relay import Remote, sniff_audio

FORMAT = 'flicks-podcasts-v1'
MAX_EPISODE_BYTES = 1024 ** 3  # a 10-hour episode at 192 kbit/s is about 860 MB
AUDIO_TYPES = {'.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.ogg': 'audio/ogg'}
# Feed media types -> the type Flicks sends when streaming; anything else is sent as MP3, the podcast norm.
STREAM_TYPES = {'audio/mpeg': 'audio/mpeg', 'audio/mp3': 'audio/mpeg', 'audio/mp4': 'audio/mp4', 'audio/x-m4a': 'audio/mp4',
                'audio/m4a': 'audio/mp4', 'audio/aac': 'audio/aac', 'audio/x-aac': 'audio/aac', 'audio/ogg': 'audio/ogg',
                'audio/opus': 'audio/ogg'}


class PodcastError(ValueError):
    """A request the user can fix (unknown episode, still downloading...)."""


def episodes_path(catalogue: Path) -> Path:
    """podcasts.json -> podcasts.episodes.json, written by flicks.datasets.podcasts."""
    return catalogue.with_suffix('.episodes.json')


@dataclass(frozen=True)
class Episode:
    id: str
    show: str
    feed: str
    link: str
    audio: str
    type: str
    published: str


class PodcastIndex:
    """{episode ID: Episode} from podcasts.episodes.json, restricted to the catalogue and validated on load."""

    def __init__(self, episodes):
        self.episodes = episodes

    @classmethod
    def load(cls, path: Path, catalogue_ids):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('format') != FORMAT or not isinstance(data.get('episodes'), dict):
            raise ValueError(f'{path} is not a Flicks podcast index')
        episodes = {}
        for content_id, entry in data['episodes'].items():
            if content_id not in catalogue_ids:
                continue  # an episode the catalogue no longer has is ignored, not an error
            fields = {name: entry.get(name) if isinstance(entry, dict) else None for name in
                      ('show', 'feed', 'link', 'audio', 'type', 'published')}
            if any(not isinstance(value, str) for value in fields.values()) or not fields['show'] \
                    or not net.public_web(fields['audio']):
                raise ValueError(f'{path} has an invalid entry for {content_id}')
            if fields['link'] and parse.urlsplit(fields['link']).scheme not in net.WEB_SCHEMES:
                fields['link'] = ''  # only ever offered as a link to the show's own page
            episodes[content_id] = Episode(content_id, **fields)
        return cls(episodes)

    def get(self, content_id):
        return self.episodes.get(content_id)

    def __len__(self):
        return len(self.episodes)

    def remotes(self):
        """{ID: Remote}: every episode can be streamed from its publisher."""
        return {key: Remote(e.audio, STREAM_TYPES.get(e.type.lower(), 'audio/mpeg'), True, e.show, e.link)
                for key, e in self.episodes.items()}


class PodcastLibrary:
    """Downloads and downloaded episodes in one folder. Thread-safe; one download at a time.

    Files are named `<episode ID><ext>` and only ever looked up by ID, so a request can never choose a
    path. A download is written to `<ID>.part` and renamed only once it is complete and sniffed as audio.
    """

    def __init__(self, index: PodcastIndex, folder: Path, fetch=net.download, limit=MAX_EPISODE_BYTES):
        self.index, self.folder, self.fetch, self.limit = index, Path(folder), fetch, limit
        self.lock = threading.Lock()
        self.jobs = {}      # ID -> {'state': 'queued' | 'downloading' | 'failed', ...}
        self.files = {}     # ID -> MediaFile, for complete downloads
        self.queue = queue.Queue()
        self.worker = None
        if self.folder.is_dir():
            for path in sorted(self.folder.iterdir()):
                if path.suffix == '.part':
                    path.unlink(missing_ok=True)  # interrupted by a restart; start again on request
                elif path.suffix in AUDIO_TYPES and path.stem in index.episodes and path.stem not in self.files:
                    self.files[path.stem] = self._media(path)

    def get(self, content_id):
        return self.index.get(content_id)

    def file(self, content_id):
        with self.lock:
            return self.files.get(content_id)

    def media(self):
        """Every downloaded episode, as playable files."""
        with self.lock:
            return list(self.files.values())

    def status(self, content_id):
        with self.lock:
            return self._status(content_id)

    def _status(self, content_id):
        if content_id in self.files:
            return {'state': 'ready', 'size': self.files[content_id].size}
        return dict(self.jobs.get(content_id) or {'state': 'remote'})

    def downloads(self):
        """{ID: status} for every episode that is downloaded, downloading, queued or failed."""
        with self.lock:
            return {content_id: self._status(content_id) for content_id in sorted({*self.files, *self.jobs})}

    def start(self, content_id):
        with self.lock:
            if self.index.get(content_id) is None:
                raise PodcastError('Not a podcast episode')
            if content_id in self.files or self.jobs.get(content_id, {}).get('state') in ('queued', 'downloading'):
                return self._status(content_id)
            self.jobs[content_id] = {'state': 'queued'}
            self.queue.put(content_id)
            if self.worker is None:
                self.worker = threading.Thread(target=self._work, name='flicks-podcast-downloads', daemon=True)
                self.worker.start()
            return self._status(content_id)

    def remove(self, content_id):
        """Delete a downloaded episode, or forget a failed download."""
        with self.lock:
            if self.index.get(content_id) is None:
                raise PodcastError('Not a podcast episode')
            if self.jobs.get(content_id, {}).get('state') in ('queued', 'downloading'):
                raise PodcastError('This episode is still downloading')
            self.jobs.pop(content_id, None)
            file = self.files.pop(content_id, None)
        if file:
            file.path.unlink(missing_ok=True)

    def wait(self):
        """Block until every queued download has finished (for tests and shutdown)."""
        self.queue.join()

    def _work(self):
        while True:
            content_id = self.queue.get()
            try:
                self._download(content_id)
            finally:
                self.queue.task_done()

    def _download(self, content_id):
        episode = self.index.get(content_id)
        part = self.folder/f'{content_id}.part'

        def progress(received, total):
            with self.lock:
                self.jobs[content_id] = {'state': 'downloading', 'received': received, 'total': total}

        progress(0, None)
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            self.fetch(episode.audio, part, self.limit, progress=progress)
            with part.open('rb') as handle:
                ext = sniff_audio(handle.read(16))
            if ext is None:
                raise ValueError('the file is not MP3, AAC, M4A or Ogg audio')
            target = self.folder/f'{content_id}{ext}'
            part.replace(target)
            with self.lock:
                self.files[content_id] = self._media(target)
                self.jobs.pop(content_id, None)
        except (OSError, ValueError, error.URLError) as exc:
            part.unlink(missing_ok=True)
            reason = f'the server answered {exc.code}' if isinstance(exc, error.HTTPError) else \
                str(getattr(exc, 'reason', None) or exc)
            with self.lock:
                self.jobs[content_id] = {'state': 'failed', 'error': f'Download failed: {reason}'}

    @staticmethod
    def _media(path: Path):
        return MediaFile(path.stem, path, AUDIO_TYPES[path.suffix], path.stat().st_size)
