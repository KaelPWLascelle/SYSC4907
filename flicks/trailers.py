"""Trailers: a YouTube video ID per catalogue film, for the Discover feed (docs/adr/0016-discover.md).

`python -m flicks.datasets.trailers` writes `<catalogue>.trailers.json` from Wikidata; here it is read
and validated. Flicks never fetches or stores the videos. The interface embeds a trailer from YouTube's
privacy-enhanced domain only after the viewer turns on online trailers, and only for the card on screen.
"""
import json
from pathlib import Path
import re

FORMAT = 'flicks-trailers-v1'
# YouTube's privacy-enhanced embeds: no cookies until the viewer plays, per YouTube's documentation.
EMBED_ORIGIN = 'https://www.youtube-nocookie.com'
YOUTUBE_ID = re.compile(r'[A-Za-z0-9_-]{11}')


def trailers_path(catalogue: Path) -> Path:
    """movielens-small.json -> movielens-small.trailers.json."""
    return catalogue.with_suffix('.trailers.json')


class TrailerIndex:
    """{content ID: YouTube video ID}."""

    def __init__(self, videos=None):
        self.videos = dict(videos or {})

    @classmethod
    def load(cls, path: Path, catalogue_ids):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('format') != FORMAT or not isinstance(data.get('trailers'), dict):
            raise ValueError(f'{path} is not a Flicks trailer index')
        videos = {}
        for content_id, video in data['trailers'].items():
            if content_id not in catalogue_ids:
                continue  # a film the catalogue no longer has is ignored, not an error
            if not isinstance(video, str) or not YOUTUBE_ID.fullmatch(video):
                raise ValueError(f'{path} has an invalid video ID for {content_id}')
            videos[content_id] = video
        return cls(videos)

    def get(self, content_id):
        return self.videos.get(content_id)

    def __len__(self):
        return len(self.videos)
