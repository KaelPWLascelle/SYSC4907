"""Wikidata and Wikipedia lookups used to enrich imported catalogues (public data only).

- Wikidata (CC0): IMDb ID -> runtime, English Wikipedia article, short description.
- Wikipedia (CC BY-SA): article -> the first sentences of its introduction, used as the description.

Requests are batched and results are cached by the caller, so a large import is polite to both
services and resumable. Nothing here runs while the app is in use.
"""
import re
import time
from urllib import parse

from ..net import get_json

WIKIDATA_SPARQL = 'https://query.wikidata.org/sparql'
WIKIPEDIA_API = 'https://en.wikipedia.org/w/api.php'
WIKIPEDIA_ARTICLE = 'https://en.wikipedia.org/wiki/'
SPARQL_BATCH = 200
EXTRACT_BATCH = 20  # the extracts API returns at most 20 introductions per request
DESCRIPTION_CHARS = 420

FILMS_QUERY = """SELECT ?imdb ?itemDescription ?seconds ?article WHERE {{
  VALUES ?imdb {{ {ids} }}
  ?item wdt:P345 ?imdb .
  OPTIONAL {{ ?item p:P2047/psn:P2047/wikibase:quantityAmount ?seconds . }}
  OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""


def _batches(items, size):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def films_by_imdb(imdb_ids, *, pause=1.0, log=print):
    """{imdb_id: {'minutes', 'article', 'description'}} for the IDs Wikidata knows.

    Runtimes come normalized to seconds; when a film has several (cuts, restorations), the shortest
    plausible one is kept, since it is the one most likely to fit the viewer's time.
    """
    found = {}
    for batch in _batches(sorted(set(imdb_ids)), SPARQL_BATCH):
        if not all(re.fullmatch(r'tt\d{7,9}', i) for i in batch):
            raise ValueError('IMDb IDs must look like tt0114709')
        query = FILMS_QUERY.format(ids=' '.join(f'"{i}"' for i in batch))
        data = get_json(WIKIDATA_SPARQL, {'query': query, 'format': 'json'}, timeout=90)
        merge_film_rows(found, data['results']['bindings'])
        log(f'  Wikidata: {len(found)} films matched so far')
        time.sleep(pause)
    return found


def merge_film_rows(found, rows):
    """Fold SPARQL result rows (one per runtime/article combination) into one record per IMDb ID."""
    for row in rows:
        imdb = row['imdb']['value']
        film = found.setdefault(imdb, {'minutes': None, 'article': None, 'description': None})
        if 'seconds' in row:
            minutes = round(float(row['seconds']['value']) / 60)
            if 1 <= minutes <= 600 and (film['minutes'] is None or minutes < film['minutes']):
                film['minutes'] = minutes
        if 'article' in row and not film['article']:
            film['article'] = parse.unquote(row['article']['value'].removeprefix(WIKIPEDIA_ARTICLE)).replace('_', ' ')
        description = row.get('itemDescription', {}).get('value')
        if description and not film['description']:
            film['description'] = description


def introductions(articles, *, pause=0.2, log=print):
    """{article title: plain-text introduction} for English Wikipedia articles."""
    found = {}
    for batch in _batches(sorted(set(articles)), EXTRACT_BATCH):
        data = get_json(WIKIPEDIA_API, {
            'action': 'query', 'prop': 'extracts', 'exintro': 1, 'explaintext': 1, 'exsentences': 3,
            'exlimit': EXTRACT_BATCH, 'redirects': 1, 'titles': '|'.join(batch), 'format': 'json', 'formatversion': 2,
        })
        query = data.get('query', {})
        # Map each requested title through normalization and redirects to the page actually returned.
        renamed = {r['from']: r['to'] for r in query.get('normalized', []) + query.get('redirects', [])}
        pages = {page['title']: page.get('extract', '') for page in query.get('pages', []) if not page.get('missing')}
        for title in batch:
            final = title
            while final in renamed:
                final = renamed[final]
            if pages.get(final):
                found[title] = pages[final]
        log(f'  Wikipedia: {len(found)} introductions so far')
        time.sleep(pause)
    return found


def clean_description(text, limit=DESCRIPTION_CHARS):
    """Whole sentences up to `limit` characters, without parentheticals (pronunciations, alt titles)."""
    text = re.sub(r'\s*\([^()]*\)', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"“])', text)
    kept = ''
    for sentence in sentences:
        candidate = f'{kept} {sentence}'.strip()
        if len(candidate) > limit:
            break
        kept = candidate
    return kept or text[:limit].rsplit(' ', 1)[0]
