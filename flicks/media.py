"""Local media library: maps video files to catalogue titles (docs/adr/0005-video-playback.md).

Files are matched by content ID (`m033.webm`) or by Jellyfin/Plex-style names
(`A Trip to the Moon (1902).mp4`, optionally inside a folder of the same name). Paths are never taken
from requests: the server only streams files this scan matched to a catalogue ID.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

VIDEO_TYPES = {'.mp4': 'video/mp4', '.m4v': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime',
               '.mkv': 'video/x-matroska'}
DIRECT_PLAY = frozenset({'.mp4', '.m4v', '.webm'})  # every current browser plays these containers
NAMED = re.compile(r'^(?P<title>.+?)\s*[(\[](?P<year>\d{4})[)\]]')


@dataclass(frozen=True)
class MediaFile:
    content_id: str
    path: Path
    media_type: str
    size: int

    @property
    def audio(self):
        return self.media_type.startswith('audio/')

    @property
    def direct_play(self):
        """False for containers some browsers cannot play (MKV, MOV); the UI warns instead of failing silently."""
        return self.path.suffix.lower() in DIRECT_PLAY or self.audio


def normalize(title):
    text = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode().lower()
    text = text.replace('&', ' and ')
    return ' '.join(re.sub(r"[^a-z0-9]+", ' ', text.replace("'", '')).split())


class MediaLibrary:
    def __init__(self, folders, catalog):
        self.files, self.unmatched, self.duplicates = {}, [], []
        by_id = {item.id: item for item in catalog}
        by_title_year = {(normalize(item.title), item.year): item.id for item in catalog}
        titles = {}
        for item in catalog:
            titles.setdefault(normalize(item.title), []).append(item.id)
        for folder in folders:
            for path in sorted(self._videos(Path(folder))):
                content_id = self._match(path.stem, by_id, by_title_year, titles)
                if content_id is None:
                    self.unmatched.append(path)
                elif content_id in self.files:
                    self.duplicates.append(path)  # first match wins; sorted order keeps it deterministic
                else:
                    self.files[content_id] = MediaFile(content_id, path, VIDEO_TYPES[path.suffix.lower()], path.stat().st_size)

    @staticmethod
    def _videos(folder):
        if not folder.is_dir():
            return []
        return [p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in VIDEO_TYPES
                and not any(part.startswith('.') for part in p.relative_to(folder).parts)]

    @staticmethod
    def _match(stem, by_id, by_title_year, titles):
        if stem in by_id:
            return stem
        named = NAMED.match(stem)
        if named:
            return by_title_year.get((normalize(named['title']), int(named['year'])))
        candidates = titles.get(normalize(stem), [])
        return candidates[0] if len(candidates) == 1 else None  # a bare title must be unambiguous

    def get(self, content_id):
        return self.files.get(content_id)

    def ids(self):
        return sorted(self.files)
