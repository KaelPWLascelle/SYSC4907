"""Match catalogue films to trailers on YouTube, for the Discover feed (docs/adr/0016-discover.md).

    python -m flicks.datasets.trailers                    # the MovieLens catalogue
    python -m flicks.datasets.trailers --catalog FILE     # any catalogue, matched by title and year
    python -m flicks.datasets.trailers --verify           # also drop videos YouTube no longer embeds

Source: the MovieLens 20M YouTube Trailers dataset (GroupLens, 2015): a trailer's YouTube ID per
MovieLens film, chosen by the dataset's authors. Catalogues imported from MovieLens match by movie ID
(`ml<movieId>`); others match by title and year. Videos are never downloaded: the index holds IDs only,
and the interface embeds a trailer from YouTube's privacy-enhanced domain once the viewer allows it.

Wikidata was considered and rejected: its YouTube IDs for films (P1651) are mostly full-length uploads,
not trailers. TMDB has current trailers but needs a personal API key.

`--verify` asks YouTube's public oEmbed endpoint about each video (sending only video IDs), because many
2015 trailers have since been removed or had embedding turned off.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from .. import net
from ..config import DEFAULT_CATALOG
from ..core import load_catalog
from ..text import title_key
from ..trailers import FORMAT, YOUTUBE_ID, trailers_path
from .movielens import DEFAULT_CACHE, parse_title

ARCHIVE_URL = 'https://files.grouplens.org/datasets/movielens/ml-20m-youtube.zip'
CHECKSUM_URL = f'{ARCHIVE_URL}.md5'
CSV_NAME = 'ml-youtube.csv'
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
OEMBED_URL = 'https://www.youtube.com/oembed'
SOURCE = 'MovieLens 20M YouTube Trailers (GroupLens)'
CITATION = ('F. Maxwell Harper and Joseph A. Konstan. 2015. The MovieLens Datasets: History and Context. '
            'ACM TiiS 5, 4: 19:1-19:19. https://doi.org/10.1145/2827872')
LICENSE = 'MovieLens terms: non-commercial research use; acknowledge in publications; no implied endorsement.'


def download(cache: Path, log=print) -> Path:
    """The trailer CSV, downloading and verifying the archive if needed."""
    path = cache/CSV_NAME
    expected = net.get(CHECKSUM_URL, 1024).decode().strip().rsplit(' ', 1)[-1].lower()
    if not re.fullmatch(r'[0-9a-f]{32}', expected):
        raise ValueError('The published trailer-dataset checksum could not be read')
    marker = cache/'ml-youtube.md5'
    if path.is_file() and marker.is_file() and marker.read_text(encoding='utf-8').strip() == expected:
        return path
    log(f'Downloading {ARCHIVE_URL}')
    data = net.get(ARCHIVE_URL, MAX_ARCHIVE_BYTES, timeout=120)
    actual = hashlib.md5(data, usedforsecurity=False).hexdigest()
    if actual != expected:
        raise ValueError(f'Trailer archive checksum mismatch (expected {expected}, got {actual})')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name = next((n for n in archive.namelist() if Path(n).name == CSV_NAME), None)
        if name is None:
            raise ValueError(f'The trailer archive has no {CSV_NAME}')
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(archive.read(name))
    marker.write_text(expected + '\n', encoding='utf-8')
    return path


def read_trailers(text):
    """[(movieId, youtubeId, title, year)] in file order, skipping malformed rows."""
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        video, movie = (row.get('youtubeId') or '').strip(), (row.get('movieId') or '').strip()
        if YOUTUBE_ID.fullmatch(video) and movie.isdigit():
            title, year = parse_title(row.get('title') or '')
            rows.append((int(movie), video, title, year))
    return rows


def match(catalog, rows):
    """{content ID: YouTube ID}: by MovieLens ID when the catalogue came from MovieLens, else by title and year.

    A film with several trailers keeps the first one listed.
    """
    by_movie, by_title = {}, {}
    for movie, video, title, year in rows:
        by_movie.setdefault(movie, video)
        by_title.setdefault((title_key(title), year), video)
    found = {}
    for item in catalog:
        if item.audio:
            continue  # podcast episodes have no trailers
        movie = int(item.id[2:]) if re.fullmatch(r'ml\d+', item.id) else None
        video = by_movie.get(movie) if movie is not None else by_title.get((title_key(item.title), item.year))
        if video:
            found[item.id] = video
    return found


def embeddable(video, timeout=15):
    """True when YouTube's oEmbed endpoint describes the video (it refuses removed or non-embeddable ones)."""
    try:
        net.get_json(OEMBED_URL, {'url': f'https://www.youtube.com/watch?v={video}', 'format': 'json'},
                     limit=64 * 1024, timeout=timeout)
        return True
    except Exception:
        return False


def verify(found, workers=8, check=embeddable, log=print):
    ids = sorted(found)
    log(f'Checking {len(ids)} videos with YouTube (video IDs only)...')
    with ThreadPoolExecutor(workers) as pool:
        ok = list(pool.map(lambda key: check(found[key]), ids))
    return {key: found[key] for key, good in zip(ids, ok, strict=True) if good}


def import_trailers(catalog_path, *, cache=DEFAULT_CACHE, check=False, log=print):
    catalog = load_catalog(catalog_path)
    rows = read_trailers(download(cache, log).read_text(encoding='utf-8'))
    found = match(catalog, rows)
    matched = len(found)
    if check:
        found = verify(found, log=log)
    out = trailers_path(Path(catalog_path))
    document = {'format': FORMAT, 'source': SOURCE, 'citation': CITATION, 'license': LICENSE,
                'verified': check, 'created': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'trailers': dict(sorted(found.items()))}
    out.write_text(json.dumps(document, indent=1) + '\n', encoding='utf-8')
    films = sum(1 for item in catalog if not item.audio)
    return {'path': out, 'films': films, 'matched': matched, 'kept': len(found)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Match catalogue films to YouTube trailers for Discover')
    parser.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG, help=f'Catalogue to match (default {DEFAULT_CATALOG})')
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--verify', action='store_true', help='Drop videos YouTube no longer embeds (sends video IDs to YouTube)')
    args = parser.parse_args(argv)
    print('Only the public trailer list is downloaded; your catalogue and ratings are not sent.')
    result = import_trailers(args.catalog, cache=args.cache, check=args.verify)
    print(f"{result['kept']} of {result['films']} films have a trailer ({result['matched']} matched) -> {result['path']}")


if __name__ == '__main__':
    main()
