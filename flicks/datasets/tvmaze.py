"""Build a TV series catalogue from TVmaze and IMDb's public ratings (docs/adr/0018-tv-series.md).

    python -m flicks.datasets.tvmaze              # the 1,000 most-voted series
    python -m flicks.datasets.tvmaze --limit 300
    flicks                                        # loads ~/.flicks/catalogs/series.json beside the films

TVmaze (https://www.tvmaze.com/api; CC BY-SA, no key) supplies the shows: names, summaries, genres, episode
length, dates, network, seasons, episode counts and covers. IMDb's non-commercial dataset (title.ratings;
personal and non-commercial use) supplies vote counts, matched by the IMDb ID TVmaze records; they choose
the shows and feed the popularity prior. Moods and intensity are estimated from genres (genres.py).
Requests stay within TVmaze's rate limit and are cached under ~/.flicks/datasets/tvmaze, so a re-run is
quick and an interrupted import resumes.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import html
import json
from pathlib import Path
import re
import time
from urllib import error

from .. import net
from ..config import DEFAULT_SERIES, HOME
from ..core import load_catalog
from ..posters import ARTWORK_FORMAT, artwork_path
from . import genres as genre_rules
from .wikimedia import clean_description

API = 'https://api.tvmaze.com'
RATINGS_URL = 'https://datasets.imdbws.com/title.ratings.tsv.gz'
MAX_RATINGS_BYTES = 64 * 1024 * 1024
MAX_PAGE_BYTES = 16 * 1024 * 1024
DEFAULT_CACHE = HOME/'datasets'/'tvmaze'
DEFAULT_LIMIT = 1000
MIN_VOTES = 5000
TYPES = frozenset({'Scripted', 'Animation', 'Documentary'})  # not talk, reality, game or news shows
PAUSE = 0.5        # TVmaze allows at least 20 requests every 10 seconds per address
RETRIES = 4
LICENSE = ('TVmaze: CC BY-SA 4.0, credited by linking each show to its TVmaze page. IMDb ratings: personal and '
           'non-commercial use only (https://developer.imdb.com/non-commercial-datasets/).')


def fetch_json(url):
    """Parsed JSON, or None for 404 (past the end of TVmaze's show index). Backs off when rate-limited."""
    for attempt in range(RETRIES + 1):
        try:
            data = net.get(url, MAX_PAGE_BYTES, accept='application/json')
            time.sleep(PAUSE)
            return json.loads(data)
        except error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code not in (429, 502, 503, 504) or attempt == RETRIES:
                raise
            time.sleep(2 ** (attempt + 1))


# ---------- the show index ----------

def trim(show):
    """The fields a catalogue entry uses, or None for a type Flicks does not show or a show without an IMDb ID."""
    imdb = (show.get('externals') or {}).get('imdb')
    if show.get('type') not in TYPES or not imdb:
        return None
    return {'id': show['id'], 'name': show.get('name'), 'type': show['type'], 'genres': show.get('genres') or [],
            'status': show.get('status'), 'minutes': show.get('averageRuntime') or show.get('runtime'),
            'premiered': show.get('premiered'), 'ended': show.get('ended'),
            'network': ((show.get('network') or show.get('webChannel')) or {}).get('name'),
            'page': show.get('url'), 'image': (show.get('image') or {}).get('medium'),
            'summary': show.get('summary'), 'imdb': imdb}


def read_index(cache: Path, fetch=fetch_json, log=print):
    """(trimmed shows, how many the index lists), one page of 250 IDs at a time until TVmaze answers 404.

    Pages are cached, except that the last cached page is read again: new shows are added at the end.
    """
    folder = cache/'shows'
    folder.mkdir(parents=True, exist_ok=True)
    cached = sorted(int(path.stem) for path in folder.glob('*.json') if path.stem.isdigit())
    shows, listed, page = [], 0, 0
    while True:
        path = folder/f'{page}.json'
        if page in cached and page != cached[-1]:
            entry = _load(path)
        else:
            data = fetch(f'{API}/shows?page={page}')
            if data is None:
                break
            entry = {'listed': len(data), 'shows': [show for show in map(trim, data) if show]}
            _save(path, entry)
        shows += entry['shows']
        listed += entry['listed']
        page += 1
        if page % 50 == 0:
            log(f'  read {page} index pages ({listed:,} shows)')
    return shows, listed


# ---------- IMDb votes ----------

def read_votes(cache: Path, wanted, refresh=False, log=print):
    """{IMDb ID: number of votes} for the IDs in `wanted`, from IMDb's ratings file (downloaded once)."""
    path = cache/'title.ratings.tsv.gz'
    if refresh or not path.is_file():
        log(f'Downloading {RATINGS_URL}')
        data = net.get(RATINGS_URL, MAX_RATINGS_BYTES, timeout=120)
        tmp = path.with_suffix('.tmp')
        tmp.write_bytes(data)
        tmp.replace(path)
    votes = {}
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle, delimiter='\t', quoting=csv.QUOTE_NONE):
            if row['tconst'] in wanted and row['numVotes'].isdigit():
                votes[row['tconst']] = int(row['numVotes'])
    return votes


# ---------- choosing and building ----------

def describe(summary):
    """TVmaze's HTML summary as whole plain-text sentences."""
    text = html.unescape(re.sub(r'<[^>]+>', ' ', summary or ''))
    return clean_description(text) if text.strip() else ''


def problem(show, votes, min_votes):
    """Why a show cannot be a catalogue title, or None."""
    if not (show['name'] or '').strip():
        return 'no name'
    if not describe(show['summary']):
        return 'no summary'
    if not show['image'] or not show['page']:
        return 'no cover'
    if type(show['minutes']) is not int or not 1 <= show['minutes'] <= 600:
        return 'no episode length'
    if not re.fullmatch(r'\d{4}-\d\d-\d\d', show['premiered'] or ''):
        return 'no premiere date'
    if not genre_rules.series_genres(show['genres'], show['type'])[0]:
        return 'no genre Flicks knows'
    if votes < min_votes:
        return f'fewer than {min_votes:,} IMDb votes'
    return None


def choose(shows, votes, limit=DEFAULT_LIMIT, min_votes=MIN_VOTES):
    """The `limit` most-voted usable shows, and why the others were left out."""
    usable, skipped = [], Counter()
    for show in shows:
        reason = problem(show, votes.get(show['imdb'], 0), min_votes)
        if reason:
            skipped[reason] += 1
        else:
            usable.append(show)
    usable.sort(key=lambda show: (-votes[show['imdb']], show['id']))
    if len(usable) > limit:
        skipped[f'beyond the {limit:,} most voted'] += len(usable) - limit
    return usable[:limit], skipped


def episode_counts(shows, cache: Path, fetch=fetch_json, log=print):
    """{TVmaze ID: (seasons, episodes)} from each show's seasons; seasons not yet aired do not count."""
    path = cache/'seasons.json'
    counts = _load(path)
    missing = [show for show in shows if str(show['id']) not in counts]
    if missing:
        log(f'Counting seasons and episodes for {len(missing)} shows')
    for done, show in enumerate(missing, 1):
        aired = [season for season in fetch(f"{API}/shows/{show['id']}/seasons") or [] if season.get('premiereDate')]
        counts[str(show['id'])] = [len(aired), sum(season.get('episodeOrder') or 0 for season in aired)]
        if done % 50 == 0:
            _save(path, counts)  # an interrupted import keeps what it counted
            log(f'  {done} of {len(missing)}')
    _save(path, counts)
    return {int(key): tuple(value) for key, value in counts.items()}


def full_size(image):
    """The original of a TVmaze cover (about 680 px wide) from its 210 px "medium_portrait" address."""
    return image.replace('/medium_portrait/', '/original_untouched/', 1) if '/medium_portrait/' in image else None


def build_catalog(shows, votes, counts):
    """(catalogue rows, artwork {ID: image and page}, skipped counts) for chosen shows."""
    rows, artwork, skipped = [], {}, Counter()
    for show in shows:
        seasons, episodes = counts.get(show['id'], (0, 0))
        if not seasons or not episodes:
            skipped['no episode count'] += 1
            continue
        genres, leftover = genre_rules.series_genres(show['genres'], show['type'])
        moods, intensity = genre_rules.estimate(genres)
        ended = int(show['ended'][:4]) if show['status'] == 'Ended' and show['ended'] else None
        content_id = f"tv{show['id']}"
        rows.append({
            'id': content_id, 'title': show['name'].strip(), 'year': int(show['premiered'][:4]), 'kind': 'series',
            'minutes': show['minutes'], 'genres': genres,
            'tags': leftover + (['miniseries'] if seasons == 1 and ended else []) or list(genres),
            'moods': moods, 'intensity': intensity, 'description': describe(show['summary']),
            'series': {'seasons': seasons, 'episodes': episodes, 'ended': ended, 'network': show['network'] or None,
                       'page': show['page'], 'votes': votes[show['imdb']]},
        })
        full = full_size(show['image'])
        artwork[content_id] = {'image': show['image'], 'page': show['page'], **({'full': full} if full else {})}
    return rows, artwork, skipped


def import_series(out: Path = DEFAULT_SERIES, cache: Path = DEFAULT_CACHE, limit=DEFAULT_LIMIT,
                  min_votes=MIN_VOTES, refresh=False, fetch=fetch_json, log=print):
    cache.mkdir(parents=True, exist_ok=True)
    log('Reading the TVmaze show index')
    shows, listed = read_index(cache, fetch, log)
    votes = read_votes(cache, {show['imdb'] for show in shows}, refresh, log)
    chosen, skipped = choose(shows, votes, limit, min_votes)
    rows, artwork, build_skipped = build_catalog(chosen, votes, episode_counts(chosen, cache, fetch, log))
    skipped.update(build_skipped)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    load_catalog(tmp)  # the same validation the app applies at startup; never write a catalogue it rejects
    tmp.replace(out)
    _save(artwork_path(out), {'format': ARTWORK_FORMAT, 'source': 'TVmaze', 'images': artwork})
    provenance = {
        'source': f'{API}/shows', 'votes': RATINGS_URL,
        'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'listed': listed, 'kept_types': sorted(TYPES), 'considered': len(shows),
        'titles': len(rows), 'skipped': dict(skipped.most_common()), 'license': LICENSE,
        'estimated_fields': {'moods': 'from genres (flicks/datasets/genres.py)',
                             'intensity': 'from genres (flicks/datasets/genres.py)'},
    }
    _save(out.with_suffix('.provenance.json'), provenance)
    return provenance


# ---------- caches ----------

def _load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build a Flicks TV series catalogue from TVmaze and IMDb votes')
    parser.add_argument('--out', type=Path, default=DEFAULT_SERIES, help=f'Catalogue to write (default {DEFAULT_SERIES})')
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE, help=f'Downloads and lookups (default {DEFAULT_CACHE})')
    parser.add_argument('--limit', type=int, default=DEFAULT_LIMIT, help=f'Most-voted series to keep (default {DEFAULT_LIMIT:,})')
    parser.add_argument('--min-votes', type=int, default=MIN_VOTES, help=f'IMDb votes a series needs (default {MIN_VOTES:,})')
    parser.add_argument('--refresh', action='store_true', help='Download IMDb votes again')
    args = parser.parse_args(argv)
    print('TVmaze data is CC BY-SA; IMDb ratings are for personal and non-commercial use.')
    result = import_series(args.out, args.cache, args.limit, args.min_votes, args.refresh)
    print(f"Wrote {result['titles']} series to {args.out}")
    for reason, count in result['skipped'].items():
        print(f'  skipped {count:,}: {reason}')
    print('Run: flicks (series load beside the films), then python -m flicks.posters for their covers')


if __name__ == '__main__':
    main()
