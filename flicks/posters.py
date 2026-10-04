"""Local poster cache. Posters are fetched once, when you run this command, never while browsing.

    python -m flicks.posters                      # fetch missing posters into ~/.flicks/posters
    python -m flicks.posters --refresh            # fetch them all again
    python -m flicks.posters --dir .local/posters

Only public catalogue titles and years leave the machine, and only during this command; what a
person browses, rates or asks for never does. Images come from English Wikipedia's page images.
Film posters are copyrighted, so the cache stays on your machine and out of git, and
posters.json records where each image came from. Without a cache, the UI draws title cards.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import ssl
import time
from urllib import error, parse, request

from .config import DEFAULT_POSTERS as DEFAULT_DIR
from .core import load_catalog

API = 'https://en.wikipedia.org/w/api.php'
USER_AGENT = 'Flicks/0.3 (SYSC 4907 student project; https://github.com/KaelPWLascelle/SYSC4907)'
MAX_BYTES = 3 * 1024 * 1024
TYPES = {'.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}


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
            # Only "<id><ext>" in this directory: a hand-edited manifest cannot point elsewhere.
            if content_id in catalog_ids and isinstance(name, str) and Path(name).suffix in TYPES \
                    and name == f'{content_id}{Path(name).suffix}' and (self.directory/name).is_file():
                self.files[content_id] = name

    def ids(self):
        return sorted(self.files)

    def read(self, content_id):
        name = self.files.get(content_id)
        if name is None:
            return None
        return (self.directory/name).read_bytes(), TYPES[Path(name).suffix]


def _ssl_context():
    """Verified TLS. python.org's macOS Python has no CA bundle until its Install Certificates step,
    so fall back to the operating system's bundle rather than ever skipping verification."""
    context = ssl.create_default_context()
    if not context.get_ca_certs() and Path('/etc/ssl/cert.pem').is_file():
        context.load_verify_locations('/etc/ssl/cert.pem')
    return context


def _get(url, limit, context=None):
    req = request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
    with request.urlopen(req, timeout=20, context=context or _ssl_context()) as reply:
        data = reply.read(limit + 1)
    if len(data) > limit:
        raise ValueError('response too large')
    return data


def candidates(item):
    return [f'{item.title} ({item.year} film)', f'{item.title} ({item.year} American film)', f'{item.title} (film)', item.title]


def plausible(page, item):
    """The page must describe a film from the catalogue year; otherwise we would show the wrong poster."""
    description = (page.get('description') or '').lower()
    return str(item.year) in description and any(w in description for w in ('film', 'documentary', 'movie'))


def find_poster(item):
    """(page title, thumbnail URL, file name) for the first plausible Wikipedia page, or None."""
    for title in candidates(item):
        query = parse.urlencode({'action': 'query', 'titles': title, 'prop': 'pageimages|description',
                                 'piprop': 'thumbnail|name', 'pithumbsize': 600, 'redirects': 1,
                                 'pilicense': 'any',  # modern posters are non-free files, excluded by default
                                 'format': 'json', 'formatversion': 2})
        pages = json.loads(_get(f'{API}?{query}', 1024 * 1024)).get('query', {}).get('pages', [])
        page = pages[0] if pages else {}
        if not page.get('missing') and page.get('thumbnail') and plausible(page, item):
            url = page['thumbnail']['source'].split('?', 1)[0]  # drop Wikipedia's utm_* tracking parameters
            return page['title'], url, page.get('pageimage')
        time.sleep(0.2)  # be gentle with the API
    return None


def fetch(catalog, directory, refresh=False, log=print):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory/'posters.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        manifest = {}
    posters = manifest.get('posters') or {}
    found = missing = 0
    for item in catalog:
        if item.id in posters and not refresh and (directory/posters[item.id]['file']).is_file():
            found += 1
            continue
        try:
            hit = find_poster(item)
            if not hit:
                log(f'  no poster: {item.title} ({item.year})')
                missing += 1
                continue
            page, url, file_name = hit
            data = _get(url, MAX_BYTES)
            ext = sniff(data)
            if not ext:
                raise ValueError('not a JPEG, PNG or WebP image')
            for old in directory.glob(f'{item.id}.*'):
                old.unlink()
            tmp = directory/f'{item.id}{ext}.tmp'
            tmp.write_bytes(data)
            tmp.replace(directory/f'{item.id}{ext}')
            posters[item.id] = {'file': f'{item.id}{ext}', 'title': item.title,
                                'page': f'https://en.wikipedia.org/wiki/{parse.quote(page.replace(" ", "_"))}',
                                'image': url, 'file_page': f'https://en.wikipedia.org/wiki/File:{parse.quote(file_name)}' if file_name else None}
            found += 1
            log(f'  ok: {item.title} <- {page}')
        except (OSError, ValueError, error.URLError) as exc:
            log(f'  failed: {item.title} ({exc})')
            missing += 1
        time.sleep(0.2)
    manifest = {'source': 'English Wikipedia page images (copyrighted posters; local cache, do not redistribute)',
                'fetched': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'posters': posters}
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    return found, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fetch catalogue posters once into a local cache')
    parser.add_argument('--catalog', type=Path, default=Path(__file__).parent/'data'/'movies.json')
    parser.add_argument('--dir', type=Path, default=DEFAULT_DIR, help=f'Poster cache (default {DEFAULT_DIR})')
    parser.add_argument('--refresh', action='store_true', help='Fetch again even when a poster is cached')
    args = parser.parse_args(argv)
    catalog = load_catalog(args.catalog)
    print(f'Fetching posters for {len(catalog)} titles into {args.dir} (only titles and years are sent)')
    found, missing = fetch(catalog, args.dir, args.refresh)
    print(f'{found} posters cached, {missing} without one (those show a title card).')


if __name__ == '__main__':
    main()
