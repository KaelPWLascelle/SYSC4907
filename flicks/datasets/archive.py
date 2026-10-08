"""Match catalogue films to public-domain copies on the Internet Archive (an explicit, user-run command).

    python -m flicks.datasets.archive                     # for the MovieLens catalogue
    python -m flicks.datasets.archive --catalog FILE      # any catalogue

Writes `<catalogue>.archive.json`, which Flicks loads automatically: a matched film gets a Play
button that streams it from the Archive through Flicks (docs/adr/0011-streaming.md).

Rights rule. The Archive's feature-film collection also holds uploads of films still under copyright,
and uploaders label their own items, so those labels are ignored. A film is used only if it is in the
public domain in the United States, where the Archive operates, by one of two tests:
- age: released at least 96 years ago (US terms for films of that era end after 95 years), or
- listed: it appears in Wikipedia's "List of films in the public domain in the United States", whose
  revision is recorded in the output.
Elements of a film (a score, a source novel) can still be protected, and other countries' terms differ.

Only public data leaves the machine: the catalogue's titles are never sent; the Archive's collection
listing and each matched item's file list are downloaded and matched here.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib import error, parse

from ..archive import FORMAT, ArchiveIndex, archive_path
from ..config import HOME
from ..core import load_catalog
from ..media import normalize
from ..net import get, get_json

DEFAULT_CATALOG = HOME/'catalogs'/'movielens-small.json'
SCRAPE = 'https://archive.org/services/search/v1/scrape'
COLLECTION = 'collection:feature_films AND mediatype:movies'
WIKIPEDIA = 'https://en.wikipedia.org/w/api.php'
PD_LIST = 'List of films in the public domain in the United States'
PUBLIC_DOMAIN_AGE = 96
# Archive file formats a browser plays, best first (the 512 kbit/s derivative is the fallback).
FORMATS = ('h.264 HD', 'h.264', 'MPEG4', 'h.264 IA', '512Kb MPEG4')
CANDIDATES = 3          # Archive items tried per film, most downloaded first
MIN_LENGTH = 0.6        # of the catalogue runtime: shorter files are trailers, clips or fragments
# Versions that are not the film as released (colourised versions can carry a new copyright).
NOT_THE_FILM = re.compile(r'(?<![a-z])(colori[sz]ed|trailers?|clips?|previews?|excerpts?|dubbed)(?![a-z])', re.I)
YEAR = re.compile(r'[(\[]\s*(\d{4})\s*[)\]]')


def parse_title(title):
    """("nosferatu", 1922) from "Nosferatu (1922) [4K]"; the year is None when the title has none."""
    title = title[0] if isinstance(title, list) and title else title if isinstance(title, str) else ''
    found = YEAR.search(title)
    base = title[:found.start()] if found else title
    base = re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', base)
    return normalize(base), int(found.group(1)) if found else None


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def item_year(item):
    """The year in the title, else the item's year field (often the upload year, so matching allows only ±1)."""
    _, year = parse_title(item.get('title'))
    if year:
        return year
    try:
        return int(str(_first(item.get('year')) or '')[:4])
    except ValueError:
        return None


def parse_public_domain_list(wikitext):
    """{(normalized title, year)} from the list article's tables (rows start with an italic, linked title)."""
    films = set()
    for row in wikitext.split('\n|-'):
        title = re.search(r"^\s*\|\s*''\[\[([^\]|]+)(?:\|([^\]]+))?\]\]''", row.lstrip('\n'))
        year = re.search(r'\|\|\s*(\d{4})\s*\|\|', row)
        if title and year:
            name = title.group(2) or re.sub(r'\s*\([^)]*\)$', '', title.group(1))
            films.add((normalize(name), int(year.group(1))))
    return films


def rights_basis(item, listed, this_year):
    """'age', 'listed' or None for a catalogue film (see the module docstring)."""
    if item.year <= this_year - PUBLIC_DOMAIN_AGE:
        return 'age'
    title = normalize(item.title)
    if any((title, year) in listed for year in (item.year - 1, item.year, item.year + 1)):
        return 'listed'
    return None


def _seconds(length):
    """Archive lengths are seconds ('4039.13') or clock time ('1:07:19')."""
    try:
        if ':' in str(length):
            total = 0.0
            for part in str(length).split(':'):
                total = total * 60 + float(part)
            return total
        return float(length)
    except (TypeError, ValueError):
        return None


def choose_file(metadata, minutes):
    """(file name, seconds) of the best browser-playable MP4 that is plausibly the whole film, or None."""
    best = None
    for entry in metadata.get('files', []):
        name, kind = entry.get('name', ''), entry.get('format')
        if not name.lower().endswith('.mp4') or kind not in FORMATS or NOT_THE_FILM.search(name):
            continue
        seconds = _seconds(entry.get('length'))
        if seconds is not None and seconds < MIN_LENGTH * minutes * 60:
            continue
        rank = (FORMATS.index(kind), -int(entry.get('height') or 0))
        if best is None or rank < best[0]:
            best = (rank, name, seconds)
    return (best[1], best[2]) if best else None


def scrape_collection(fetch=get, log=print):
    """Every item in the feature-film collection: identifier, title, year and downloads (about 30,000)."""
    items, cursor = [], None
    while True:
        params = {'q': COLLECTION, 'fields': 'identifier,title,year,downloads', 'count': 10000}
        if cursor:
            params['cursor'] = cursor
        page = json.loads(fetch(f'{SCRAPE}?{parse.urlencode(params)}', 64 * 1024 * 1024, accept='application/json', timeout=120))
        items += page.get('items', [])
        cursor = page.get('cursor')
        log(f'  listed {len(items)} Archive items')
        if not cursor:
            return items


def fetch_public_domain_list(fetch_json=get_json):
    data = fetch_json(WIKIPEDIA, {'action': 'parse', 'page': PD_LIST, 'prop': 'wikitext|revid', 'format': 'json',
                                  'formatversion': 2})['parse']
    return parse_public_domain_list(data['wikitext']), data.get('revid')


def match(catalog, items, listed, this_year):
    """({content ID: (catalogue item, basis, candidate Archive items)}, skip reasons)."""
    by_title = {}
    for item in items:
        identifier, title = item.get('identifier'), _first(item.get('title'))
        if not isinstance(identifier, str) or NOT_THE_FILM.search(f'{identifier} {title or ""}'):
            continue
        name, _ = parse_title(title)
        if name:
            by_title.setdefault(name, []).append(item)
    found, skipped = {}, Counter()
    for film in catalog:
        candidates = [i for i in by_title.get(normalize(film.title), [])
                      if item_year(i) is not None and abs(item_year(i) - film.year) <= 1]
        if not candidates:
            continue
        basis = rights_basis(film, listed, this_year)
        if basis is None:
            skipped['on the Archive but not known to be public domain in the US'] += 1
            continue
        candidates.sort(key=lambda i: (-int(_first(i.get('downloads')) or 0), i['identifier']))
        found[film.id] = (film, basis, candidates[:CANDIDATES])
    return found, skipped


def import_archive(catalog_path: Path, fetch=get, fetch_json=get_json, log=print, pause=0.2, this_year=None):
    this_year = this_year or datetime.now(timezone.utc).year
    catalog = load_catalog(catalog_path)
    log(f"Reading Wikipedia's {PD_LIST!r}")
    listed, revision = fetch_public_domain_list(fetch_json)
    log('Listing the Internet Archive feature-film collection')
    matched, skipped = match(catalog, scrape_collection(fetch, log), listed, this_year)
    log(f'{len(matched)} catalogue films have a public-domain copy to check')
    films = {}
    for content_id, (film, basis, candidates) in matched.items():
        for candidate in candidates:
            identifier = candidate['identifier']
            try:
                metadata = json.loads(fetch(f'https://archive.org/metadata/{parse.quote(identifier)}', 16 * 1024 * 1024,
                                            accept='application/json'))
            except (OSError, ValueError, error.URLError):
                continue
            finally:
                time.sleep(pause)
            chosen = choose_file(metadata, film.minutes)
            if chosen:
                name, seconds = chosen
                films[content_id] = {
                    'title': film.title, 'identifier': identifier, 'file': name, 'seconds': seconds, 'basis': basis,
                    'url': f'https://archive.org/download/{parse.quote(identifier)}/{parse.quote(name)}',
                    'page': f'https://archive.org/details/{parse.quote(identifier)}'}
                log(f'  {film.title} ({film.year}) <- {identifier} [{basis}]')
                break
        else:
            skipped['no complete, browser-playable MP4'] += 1
    out = archive_path(catalog_path)
    index = {'format': FORMAT, 'fetched': datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'rights': {'rule': f'released at least {PUBLIC_DOMAIN_AGE} years ago, or listed by Wikipedia',
                        'wikipedia': f'https://en.wikipedia.org/w/index.php?oldid={revision}' if revision else PD_LIST},
             'skipped': dict(skipped), 'films': dict(sorted(films.items()))}
    tmp = out.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(index, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    ArchiveIndex.load(tmp, {item.id for item in catalog})  # never leave a file the app would reject
    tmp.replace(out)
    return {'films': len(films), 'skipped': dict(skipped), 'path': out}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Match catalogue films to public-domain copies on the Internet Archive')
    parser.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG, help=f'Catalogue to match (default {DEFAULT_CATALOG})')
    args = parser.parse_args(argv)
    print('Only public listings are downloaded; your catalogue and ratings are not sent. Films are streamed from '
          'the Archive when you press Play and are never re-hosted.')
    result = import_archive(args.catalog)
    print(f"{result['films']} films can be streamed -> {result['path']}")
    for reason, count in sorted(result['skipped'].items()):
        print(f'  skipped {count}: {reason}')


if __name__ == '__main__':
    main()
