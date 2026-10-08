"""Public-domain films on the Internet Archive, matched to catalogue titles (docs/adr/0011-streaming.md).

`python -m flicks.datasets.archive` writes `<catalogue>.archive.json`; here it is read and validated,
and each matched film becomes a Remote that plays through the relay (flicks/relay.py).
"""
import json
from pathlib import Path
from urllib import parse

from . import net
from .relay import Remote

FORMAT = 'flicks-archive-v1'
SOURCE = 'Internet Archive'
VIDEO_TYPES = {'.mp4': 'video/mp4', '.webm': 'video/webm'}


def archive_path(catalogue: Path) -> Path:
    """movielens-small.json -> movielens-small.archive.json."""
    return catalogue.with_suffix('.archive.json')


def is_archive_url(url):
    host = (parse.urlsplit(url).hostname or '').lower()
    return net.public_web(url) and (host == 'archive.org' or host.endswith('.archive.org'))


class ArchiveIndex:
    """{content ID: Remote} for films with a public-domain copy on the Internet Archive."""

    def __init__(self, films):
        self.films = films

    @classmethod
    def load(cls, path: Path, catalogue_ids):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('format') != FORMAT or not isinstance(data.get('films'), dict):
            raise ValueError(f'{path} is not a Flicks archive index')
        films = {}
        for content_id, entry in data['films'].items():
            if content_id not in catalogue_ids:
                continue  # a film the catalogue no longer has is ignored, not an error
            url = entry.get('url') if isinstance(entry, dict) else None
            page = entry.get('page') if isinstance(entry, dict) else None
            media_type = VIDEO_TYPES.get(Path(parse.urlsplit(url).path).suffix.lower()) if isinstance(url, str) else None
            if not isinstance(url, str) or not is_archive_url(url) or media_type is None \
                    or not isinstance(page, str) or (page and not is_archive_url(page)):
                raise ValueError(f'{path} has an invalid entry for {content_id}')
            films[content_id] = Remote(url, media_type, False, SOURCE, page)
        return cls(films)

    def remotes(self):
        return dict(self.films)

    def __len__(self):
        return len(self.films)
