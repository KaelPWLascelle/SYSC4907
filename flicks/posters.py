"""Local poster cache. Posters are fetched once, when you run this command, never while browsing.

    python -m flicks.posters                      # every catalogue Flicks loads (most popular 3,000 films first)
    python -m flicks.posters --all                # every film
    python -m flicks.posters --refresh            # fetch them all again
    python -m flicks.posters --catalog FILE --dir .local/posters

Sources:
- films with a known English Wikipedia article (the MovieLens import records them): the article's
  page image, looked up 50 articles per request;
- podcast episodes: the artwork in their feed (usually the show's, downloaded once per show);
- other catalogues (the bundled demo): a Wikipedia search by title and year.

Only public catalogue titles, years and image addresses leave the machine, and only during this
command; what a person browses, rates or asks for never does. Posters are copyrighted, so the cache
stays on your machine and out of git, and posters.json records where each image came from. Without a
cache, the UI draws title cards.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib import error, parse

from .config import DEFAULT_CATALOG, DEFAULT_PODCASTS
from .config import DEFAULT_POSTERS as DEFAULT_DIR
from .core import load_catalog
from .net import get as _get
from .net import get_json

API = 'https://en.wikipedia.org/w/api.php'
MAX_BYTES = 3 * 1024 * 1024
MAX_SHOW_BYTES = 12 * 1024 * 1024  # podcast feeds often publish 3000 px artwork
WIDTH = 330             # one of Wikimedia's standard thumbnail widths (others are rendered on demand and throttled)
BATCH = 50              # titles per Wikipedia query (the API's limit)
WORKERS = 2             # parallel image downloads; Wikimedia rate-limits clients that ask for more
RETRIES = 4             # after "too many requests" or a temporary failure, waiting longer each time
DEFAULT_LIMIT = 3000
TYPES = {'.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
# Episodes of one show share their show's artwork, cached once as show-<hash>.<ext>.
SHARED = re.compile(r'show-[0-9a-f]{12}')


def sniff(data):
    """File extension from magic bytes, or None. Never trust the server's content type."""
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    return None


class PosterLibrary:
    """Read-only view of a poster cache, limited to catalogue IDs and files the manifest names."""

    def __init__(self, directory, catalog_ids):
        self.directory, self.files = Path(directory), {}
        try:
            manifest = json.loads((self.directory/'posters.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        for content_id, entry in (manifest.get('posters') or {}).items():
            name = entry.get('file') if isinstance(entry, dict) else None
            # Only "<id><ext>" or a shared show file in this directory: a hand-edited manifest cannot point
            # elsewhere, nor give one title another title's poster.
            stem, ext = (Path(name).stem, Path(name).suffix) if isinstance(name, str) else ('', '')
            if content_id in catalog_ids and name == f'{stem}{ext}' and ext in TYPES \
                    and (stem == content_id or SHARED.fullmatch(stem)) and (self.directory/name).is_file():
                self.files[content_id] = name

    def ids(self):
        return sorted(self.files)

    def read(self, content_id):
        name = self.files.get(content_id)
        if name is None:
            return None
        return (self.directory/name).read_bytes(), TYPES[Path(name).suffix]


@dataclass(frozen=True)
class Job:
    """One title's poster: where to get it, the cache file stem (shared by a show's episodes) and its credit page."""
    content_id: str
    title: str
    image: str
    stem: str
    page: str | None


# ---------- finding images ----------

def wikipedia_page_images(articles, fetch_json=get_json, log=print):
    """{article: (thumbnail URL, page URL)} for English Wikipedia articles, 50 per request; redirects followed."""
    found = {}
    for start in range(0, len(articles), BATCH):
        chunk = articles[start:start + BATCH]
        data = fetch_json(API, {'action': 'query', 'titles': '|'.join(chunk), 'prop': 'pageimages',
                                'piprop': 'thumbnail', 'pithumbsize': WIDTH, 'redirects': 1, 'format': 'json',
                                'formatversion': 2, 'pilicense': 'any'})  # film posters are non-free files
        query = data.get('query', {})
        renamed = {row['from']: row['to'] for row in query.get('normalized', []) + query.get('redirects', [])}
        images = {page['title']: page['thumbnail']['source'].split('?', 1)[0]  # drop Wikipedia's utm_* parameters
                  for page in query.get('pages', []) if page.get('thumbnail')}
        for article in chunk:
            title = article
            for _ in range(3):  # normalisation, then a redirect, possibly chained
                title = renamed.get(title, title)
            if title in images:
                found[article] = (images[title], f'https://en.wikipedia.org/wiki/{parse.quote(title.replace(" ", "_"))}')
        if start + BATCH < len(articles):
            log(f'  looked up {start + BATCH} of {len(articles)} articles')
            time.sleep(0.1)
    return found


def candidates(item):
    return [f'{item.title} ({item.year} film)', f'{item.title} ({item.year} American film)', f'{item.title} (film)', item.title]


def plausible(page, item):
    """The page must describe a film from the catalogue year; otherwise we would show the wrong poster."""
    description = (page.get('description') or '').lower()
    return str(item.year) in description and any(w in description for w in ('film', 'documentary', 'movie'))


def find_poster(item, fetch_json=get_json):
    """(thumbnail URL, page URL) for the first plausible Wikipedia page found by title search, or None."""
    for title in candidates(item):
        pages = fetch_json(API, {'action': 'query', 'titles': title, 'prop': 'pageimages|description',
                                 'piprop': 'thumbnail', 'pithumbsize': WIDTH, 'redirects': 1, 'pilicense': 'any',
                                 'format': 'json', 'formatversion': 2}).get('query', {}).get('pages', [])
        page = pages[0] if pages else {}
        if not page.get('missing') and page.get('thumbnail') and plausible(page, item):
            return page['thumbnail']['source'].split('?', 1)[0], \
                f'https://en.wikipedia.org/wiki/{parse.quote(page["title"].replace(" ", "_"))}'
        time.sleep(0.2)  # be gentle with the API
    return None


# ---------- fetching ----------

def download_image(url, limit=MAX_BYTES):
    for attempt in range(RETRIES + 1):
        try:
            data = _get(url, limit, accept='image/*')
            break
        except error.HTTPError as exc:
            if exc.code not in (429, 502, 503, 504) or attempt == RETRIES:
                raise
            wait = exc.headers.get('Retry-After') if exc.headers else None
            time.sleep(float(wait) if wait and wait.isdigit() else 2 ** (attempt + 1))
    ext = sniff(data)
    if not ext:
        raise ValueError('not a JPEG, PNG or WebP image')
    return data, ext


def fetch(jobs, directory, refresh=False, fetch_image=download_image, log=print):
    """Download each distinct image once and record every title's file in posters.json. Returns (found, missing)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory/'posters.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        manifest = {}
    posters = manifest.get('posters') or {}

    def cached(job):
        entry = posters.get(job.content_id)
        return not refresh and isinstance(entry, dict) and entry.get('image') == job.image \
            and (directory/str(entry.get('file'))).is_file()

    todo = [job for job in jobs if not cached(job)]
    by_image = {}
    for job in todo:
        by_image.setdefault(job.image, []).append(job)

    def get_one(image):
        shared = SHARED.fullmatch(by_image[image][0].stem)
        try:
            return image, fetch_image(image, MAX_SHOW_BYTES if shared else MAX_BYTES), None
        except (OSError, ValueError, error.URLError) as exc:
            return image, None, exc

    found = len(jobs) - len(todo)
    with ThreadPoolExecutor(WORKERS) as pool:
        for done, (image, result, problem) in enumerate(pool.map(get_one, by_image), 1):
            waiting = by_image[image]
            if result is None:
                log(f'  failed: {waiting[0].title} ({problem})')
                continue
            data, ext = result
            stem = waiting[0].stem
            for old in directory.glob(f'{stem}.*'):
                if old.suffix in TYPES:
                    old.unlink()
            tmp = directory/f'{stem}{ext}.tmp'
            tmp.write_bytes(data)
            tmp.replace(directory/f'{stem}{ext}')
            for job in waiting:
                posters[job.content_id] = {'file': f'{stem}{ext}', 'title': job.title, 'image': image, 'page': job.page}
            found += len(waiting)
            if done % 250 == 0:
                log(f'  {done} of {len(by_image)} images')
                manifest_path.write_text(json.dumps({**manifest, 'posters': posters}, ensure_ascii=False) + '\n',
                                         encoding='utf-8')  # an interrupted run keeps what it fetched
    manifest = {'source': 'English Wikipedia page images and podcast feed artwork '
                          '(copyrighted; local cache for personal use, do not redistribute)',
                'fetched': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'posters': posters}
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    prune(directory, posters)
    return found, len(jobs) - found


def prune(directory: Path, posters):
    """Delete cached images no title refers to any more (a replaced show image, a re-fetched poster)."""
    kept = {entry.get('file') for entry in posters.values() if isinstance(entry, dict)}
    for path in directory.iterdir():
        if path.suffix in TYPES and path.name not in kept:
            path.unlink()


# ---------- planning ----------

def popularity(catalog_path: Path):
    """{content ID: public likes} from the catalogue's neighbour file, for ordering; {} when there is none."""
    try:
        data = json.loads(catalog_path.with_suffix('.neighbours.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in (data.get('popularity') or {}).items() if isinstance(v, int)}


def plan(catalog_path: Path, limit=DEFAULT_LIMIT, articles=None, episodes=None, fetch_json=get_json, log=print):
    """The poster jobs for one catalogue: films (most liked first, up to `limit`) and podcast episodes."""
    from .datasets.movielens import wikipedia_articles  # build-time helper; avoids a cycle at import time
    from .podcasts import PodcastIndex, episodes_path

    catalog = load_catalog(catalog_path)
    if episodes is None and episodes_path(catalog_path).is_file():
        episodes = PodcastIndex.load(episodes_path(catalog_path), {item.id for item in catalog}).episodes
    episodes = episodes or {}
    articles = wikipedia_articles() if articles is None else articles
    jobs = []
    for item in catalog:
        episode = episodes.get(item.id)
        if episode and episode.image:
            stem = 'show-' + hashlib.sha1(episode.image.encode()).hexdigest()[:12]
            jobs.append(Job(item.id, item.title, episode.image, stem, episode.link or None))
    films = [item for item in catalog if item.id not in episodes]
    likes = popularity(catalog_path)
    films.sort(key=lambda item: -likes.get(item.id, 0))  # stable: catalogue order among equals
    films = films if limit is None else films[:limit]
    known = [item for item in films if item.id in articles]
    if known:
        log(f'Looking up page images for {len(known)} films on English Wikipedia')
        images = wikipedia_page_images(sorted({articles[item.id] for item in known}), fetch_json, log)
        for item in known:
            if articles[item.id] in images:
                image, page = images[articles[item.id]]
                jobs.append(Job(item.id, item.title, image, item.id, page))
    unknown = [item for item in films if item.id not in articles]
    if unknown and len(unknown) <= 500:  # a title search is several requests per film: small catalogues only
        log(f'Searching Wikipedia for {len(unknown)} films by title')
        for item in unknown:
            hit = find_poster(item, fetch_json)
            if hit:
                jobs.append(Job(item.id, item.title, hit[0], item.id, hit[1]))
    return jobs


def default_catalogs():
    from .datasets.movielens import DEFAULT_OUT as MOVIELENS
    films = MOVIELENS if MOVIELENS.is_file() else DEFAULT_CATALOG
    return [films, DEFAULT_PODCASTS] if DEFAULT_PODCASTS.is_file() else [films]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fetch catalogue posters once into a local cache')
    parser.add_argument('--catalog', type=Path, action='append', help='Catalogue (repeatable; default: the ones Flicks loads)')
    parser.add_argument('--dir', type=Path, default=DEFAULT_DIR, help=f'Poster cache (default {DEFAULT_DIR})')
    parser.add_argument('--refresh', action='store_true', help='Fetch again even when a poster is cached')
    parser.add_argument('--limit', type=int, default=DEFAULT_LIMIT, help=f'Most popular films per catalogue (default {DEFAULT_LIMIT})')
    parser.add_argument('--all', action='store_true', help='Every film, however many')
    args = parser.parse_args(argv)
    jobs = []
    for catalog in args.catalog or default_catalogs():
        print(f'Planning posters for {catalog} (only titles, years and image addresses are sent)')
        jobs += plan(catalog, None if args.all else args.limit)
    print(f'Fetching {len({job.image for job in jobs})} images for {len(jobs)} titles into {args.dir}')
    found, missing = fetch(jobs, args.dir, args.refresh)
    print(f'{found} titles have a poster{f", {missing} could not be fetched" if missing else ""}. '
          'Titles without one show a title card.')


if __name__ == '__main__':
    main()
