"""Build a Flicks catalogue from the MovieLens "latest-small" dataset (about 9,700 films).

    python -m flicks.datasets.movielens          # download, verify, enrich, write the catalogue
    flicks --catalog ~/.flicks/catalogs/movielens-small.json --db ~/.flicks/movielens.sqlite3

MovieLens supplies titles, years, genres, user tags and IMDb IDs. Runtimes and descriptions come
from Wikidata and Wikipedia, matched by IMDb ID (see wikimedia.py). Moods and intensity are
genre-based estimates (see genres.py). Everything is cached under ~/.flicks/, so re-running is quick
and an interrupted import resumes.

MovieLens is for non-commercial research use and must be cited: F. Maxwell Harper and Joseph A.
Konstan. 2015. The MovieLens Datasets: History and Context. ACM TiiS 5, 4: 19:1-19:19.
https://doi.org/10.1145/2827872. The derived catalogue carries the same conditions.
"""
import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import zipfile

from .. import net
from ..config import HOME
from ..core import load_catalog
from . import genres as genre_rules
from . import neighbours, wikimedia

DATASET = 'ml-latest-small'
ARCHIVE_URL = f'https://files.grouplens.org/datasets/movielens/{DATASET}.zip'
CHECKSUM_URL = f'{ARCHIVE_URL}.md5'
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
DEFAULT_CACHE = HOME/'datasets'
DEFAULT_OUT = HOME/'catalogs'/'movielens-small.json'
TAGS_PER_TITLE = 5
CITATION = ('F. Maxwell Harper and Joseph A. Konstan. 2015. The MovieLens Datasets: History and Context. '
            'ACM Transactions on Interactive Intelligent Systems (TiiS) 5, 4: 19:1-19:19. https://doi.org/10.1145/2827872')
LICENSE = ('MovieLens: non-commercial research use; acknowledge in publications; redistribution only under the same '
           'conditions; no implied endorsement by the University of Minnesota or GroupLens.')

TITLE_YEAR = re.compile(r'^(?P<title>.*?)\s*\((?P<year>\d{4})(?:[-–]\d{0,4})?\)\s*$')
AKA = re.compile(r'\s*\((?:a\.k\.a\.|aka)\s[^)]*\)', re.IGNORECASE)
TRAILING_ARTICLE = re.compile(r'^(?P<rest>.+), (?P<article>The|A|An|Les|Le|La|L\'|Il|El|Das|Der|Die|Los|Las)$')


@dataclass(frozen=True)
class Movie:
    movie_id: int
    title: str
    year: int
    genres: tuple[str, ...]


def parse_title(raw):
    """'Matrix, The (1999)' -> ('The Matrix', 1999). Returns (title, None) when there is no year."""
    raw = AKA.sub('', raw.strip())
    match = TITLE_YEAR.match(raw)
    title, year = (match['title'], int(match['year'])) if match else (raw, None)
    # Alternate titles in parentheses ('City of Lost Children, The (Cité des enfants perdus, La)').
    title = re.sub(r'\s*\([^()]*\)\s*$', '', title).strip() or title.strip()
    article = TRAILING_ARTICLE.match(title)
    if article:
        separator = '' if article['article'].endswith("'") else ' '
        title = f"{article['article']}{separator}{article['rest']}"
    return title, year


# ---------- download ----------

def download(cache: Path, log=print) -> Path:
    """The extracted dataset folder, downloading and verifying the archive if needed."""
    folder = cache/DATASET
    expected = net.get(CHECKSUM_URL, 1024).decode().strip().rsplit(' ', 1)[-1].lower()
    if not re.fullmatch(r'[0-9a-f]{32}', expected):
        raise ValueError('The published MovieLens checksum could not be read')
    marker = folder/'.md5'
    if marker.is_file() and marker.read_text(encoding='utf-8').strip() == expected:
        return folder
    log(f'Downloading {ARCHIVE_URL}')
    data = net.get(ARCHIVE_URL, MAX_ARCHIVE_BYTES, timeout=120)
    actual = hashlib.md5(data, usedforsecurity=False).hexdigest()
    if actual != expected:
        raise ValueError(f'MovieLens archive checksum mismatch (expected {expected}, got {actual})')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or path.parts[0] != DATASET:
                raise ValueError(f'Unexpected path in the MovieLens archive: {name}')
        archive.extractall(cache)
    marker.write_text(expected + '\n', encoding='utf-8')
    return folder


# ---------- parse ----------

def _rows(path):
    with path.open(encoding='utf-8', newline='') as handle:
        yield from csv.DictReader(handle)


def read_movies(folder: Path):
    movies, skipped = [], Counter()
    for row in _rows(folder/'movies.csv'):
        title, year = parse_title(row['title'])
        genres = genre_rules.normalize_genres(row['genres'].split('|'))
        if year is None:
            skipped['no year in the MovieLens title'] += 1
        elif not genres:
            skipped['no genres'] += 1
        else:
            movies.append(Movie(int(row['movieId']), title, year, tuple(genres)))
    return movies, skipped


def read_links(folder: Path):
    """movieId -> IMDb ID ('tt0114709')."""
    return {int(row['movieId']): f"tt{int(row['imdbId']):07d}" for row in _rows(folder/'links.csv') if row['imdbId']}


def read_tags(folder: Path, limit=TAGS_PER_TITLE):
    """movieId -> the most-applied user tags (short, lowercase, deduplicated)."""
    counts = {}
    for row in _rows(folder/'tags.csv'):
        tag = ' '.join(row['tag'].lower().split())
        if 2 <= len(tag) <= 30 and len(tag.split()) <= 3:
            counts.setdefault(int(row['movieId']), Counter())[tag] += 1
    return {movie_id: [tag for tag, _ in c.most_common(limit)] for movie_id, c in counts.items()}


# ---------- build ----------

def build_catalog(movies, links, tags, films, intros):
    """Validated catalogue rows plus a count of skipped titles by reason."""
    rows, skipped = [], Counter()
    for movie in movies:
        film = films.get(links.get(movie.movie_id, ''))
        if film is None:
            skipped['not found on Wikidata'] += 1
            continue
        if not film['minutes']:
            skipped['no runtime on Wikidata'] += 1
            continue
        text = intros.get(film['article'] or '') or film['description'] or ''
        description = wikimedia.clean_description(text)
        if not description:
            skipped['no description'] += 1
            continue
        moods, intensity = genre_rules.estimate(movie.genres)
        rows.append({
            'id': f'ml{movie.movie_id}', 'title': movie.title, 'year': movie.year, 'kind': 'movie',
            'minutes': film['minutes'], 'genres': list(movie.genres),
            'tags': tags.get(movie.movie_id) or list(movie.genres),
            'moods': moods, 'intensity': intensity, 'description': description,
        })
    return rows, skipped


# ---------- caches ----------

def _load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    tmp.replace(path)


# Lookups are saved after every chunk, so an interrupted import resumes where it stopped.
SAVE_EVERY = 1000


def _cached_lookup(path, keys, lookup, label, log):
    """Fill the cache at `path` for `keys` it lacks; a missing result is cached as None (looked up, not found)."""
    cache = _load(path)
    missing = [k for k in keys if k not in cache]
    if missing:
        log(f'{label}: {len(missing)} to look up')
    for start in range(0, len(missing), SAVE_EVERY):
        chunk = missing[start:start + SAVE_EVERY]
        found = lookup(chunk, log=log)
        cache.update({k: found.get(k) for k in chunk})
        _save(path, cache)
    return {k: v for k, v in cache.items() if v}


def _enrich(cache: Path, imdb_ids, log):
    """Wikidata films and Wikipedia introductions, fetching only what the caches lack."""
    films = _cached_lookup(cache/'wikidata-films.json', imdb_ids, wikimedia.films_by_imdb, 'Wikidata', log)
    articles = sorted({f['article'] for f in films.values() if f['article']})
    intros = _cached_lookup(cache/'wikipedia-introductions.json', articles, wikimedia.introductions, 'Wikipedia', log)
    return films, intros


def import_movielens(out: Path = DEFAULT_OUT, cache: Path = DEFAULT_CACHE, log=print):
    folder = download(cache, log)
    movies, skipped = read_movies(folder)
    links, tags = read_links(folder), read_tags(folder)
    films, intros = _enrich(cache, sorted({links[m.movie_id] for m in movies if m.movie_id in links}), log)
    rows, build_skipped = build_catalog(movies, links, tags, films, intros)
    skipped.update(build_skipped)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    load_catalog(tmp)  # the same validation the app applies at startup; never write a catalogue it rejects
    tmp.replace(out)
    provenance = {
        'dataset': DATASET, 'source': ARCHIVE_URL,
        'md5': (folder/'.md5').read_text(encoding='utf-8').strip(),
        'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'titles': len(rows), 'skipped': dict(skipped.most_common()),
        'license': LICENSE, 'citation': CITATION,
        'enrichment': {'runtimes and articles': 'Wikidata (CC0)',
                       'descriptions': 'English Wikipedia introductions (CC BY-SA 4.0)'},
        'estimated_fields': {'moods': 'from genres (flicks/datasets/genres.py)',
                             'intensity': 'from genres (flicks/datasets/genres.py)'},
        'ratings': str(folder/'ratings.csv'),
    }
    _save(out.with_suffix('.provenance.json'), provenance)
    provenance['neighbours'] = _build_neighbours(out, folder/'ratings.csv', {row['id'] for row in rows}, log)
    return provenance


def _build_neighbours(catalogue: Path, ratings: Path, catalogue_ids, log):
    """Collaborative-filtering neighbours next to the catalogue, when NumPy (the datasets extra) is installed."""
    if importlib.util.find_spec('numpy') is None:
        log('Skipping collaborative filtering: pip install -e ".[datasets]" and re-run to add it')
        return None
    built = neighbours.build(neighbours.read_ratings(ratings), catalogue_ids)
    if not built:
        return None
    path = neighbours.sidecar(catalogue)
    neighbours.write(built, path, str(ratings), catalogue_ids)
    log(f'Collaborative filtering: {len(built)} titles have neighbours -> {path}')
    return str(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build a Flicks catalogue from MovieLens (latest-small)')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT, help=f'Catalogue to write (default {DEFAULT_OUT})')
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE, help=f'Downloads and lookups (default {DEFAULT_CACHE})')
    args = parser.parse_args(argv)
    print('MovieLens is for non-commercial research use; cite Harper & Konstan (2015) in publications.')
    result = import_movielens(args.out, args.cache)
    print(f"Wrote {result['titles']} titles to {args.out}")
    for reason, count in result['skipped'].items():
        print(f'  skipped {count}: {reason}')
    print(f'Run: flicks --catalog {args.out} --db {HOME/"movielens.sqlite3"}')


if __name__ == '__main__':
    main()
