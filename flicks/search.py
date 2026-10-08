"""Catalogue lookup and everyday-language search, in memory (docs/adr/0007-catalogue-artifact.md).

A query is first read for what it asks to narrow by: a decade or year ("from the 90s", "before 1980"),
a length ("under 90 minutes"), a kind ("podcasts", "films"), genres ("funny", "sci-fi") and moods
("chill"). Whatever is left is matched as words against titles, shows, genres, tags and plot
descriptions, so "keaton" finds Buster Keaton's films and "tom hanks" finds his. Results rank by where
the words matched (title first), then by how widely liked a title is. A query that is itself part of a
title ("scary movie", "star wars") is searched as words, never reinterpreted.
"""
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
import math
import re

from .media import normalize

STOP_WORDS = frozenset({
    'a', 'an', 'and', 'any', 'anything', 'about', 'are', 'at', 'be', 'best', 'by', 'can', 'do', 'find', 'for', 'from',
    'fun', 'get', 'give', 'good', 'great', 'i', 'im', 'in', 'into', 'is', 'it', 'like', 'looking', 'me', 'more', 'my',
    'of', 'on', 'or', 'please', 'recommend', 'recommendation', 'see', 'set', 'show', 'some', 'something', 'that', 'the',
    'them', 'there', 'these', 'this', 'to', 'want', 'watch', 'we', 'what', 'with', 'would', 'you'})

KIND_WORDS = {'podcast': 'episode', 'podcasts': 'episode', 'episode': 'episode', 'episodes': 'episode',
              'listen': 'episode', 'movie': 'movie', 'movies': 'movie', 'film': 'movie', 'films': 'movie',
              'flick': 'movie', 'flicks': 'movie'}

# Everyday words -> catalogue genres (film genres and podcast categories). Only genres the catalogue has are used.
GENRE_WORDS = {
    'funny': ('comedy',), 'comedy': ('comedy',), 'comedies': ('comedy',), 'hilarious': ('comedy',),
    'romcom': ('romance', 'comedy'), 'rom com': ('romance', 'comedy'),
    'scary': ('horror',), 'horror': ('horror',), 'spooky': ('horror',), 'creepy': ('horror',), 'frightening': ('horror',),
    'sci fi': ('science-fiction',), 'scifi': ('science-fiction',), 'science fiction': ('science-fiction',),
    'romantic': ('romance',), 'romance': ('romance',), 'love story': ('romance',),
    'animated': ('animation',), 'animation': ('animation',), 'cartoon': ('animation',), 'cartoons': ('animation',),
    'kids': ('family',), 'family': ('family',), 'childrens': ('family',),
    'documentary': ('documentary',), 'documentaries': ('documentary',),
    'thriller': ('thriller',), 'thrillers': ('thriller',), 'suspense': ('thriller',),
    'action': ('action',), 'adventure': ('adventure',), 'adventures': ('adventure',),
    'crime': ('crime',), 'gangster': ('crime',), 'heist': ('crime',),
    'mystery': ('mystery',), 'mysteries': ('mystery',), 'whodunit': ('mystery',),
    'war': ('war',), 'western': ('western',), 'westerns': ('western',), 'musical': ('musical',), 'musicals': ('musical',),
    'fantasy': ('fantasy',), 'drama': ('drama',), 'dramas': ('drama',), 'noir': ('film-noir',), 'film noir': ('film-noir',),
    'history': ('history',), 'science': ('science',), 'technology': ('technology',), 'tech': ('technology',),
    'business': ('business',), 'true crime': ('true-crime',), 'news': ('news',), 'sports': ('sports',),
    'health': ('health-and-fitness',), 'fitness': ('health-and-fitness',), 'education': ('education',),
}
MOOD_WORDS = {'relaxing': 'relaxing', 'chill': 'relaxing', 'cozy': 'relaxing', 'calm': 'relaxing',
              'uplifting': 'uplifting', 'feel good': 'uplifting', 'heartwarming': 'uplifting', 'happy': 'uplifting',
              'tense': 'tense', 'gripping': 'tense', 'edge of my seat': 'tense',
              'thoughtful': 'reflective', 'reflective': 'reflective', 'moving': 'reflective',
              'curious': 'curious', 'mind bending': 'curious', 'clever': 'curious'}
DECADE_WORDS = {'twenties': 1920, 'thirties': 1930, 'forties': 1940, 'fifties': 1950, 'sixties': 1960,
                'seventies': 1970, 'eighties': 1980, 'nineties': 1990}
ROMAN = {'1': 'i', '2': 'ii', '3': 'iii', '4': 'iv', '5': 'v', '6': 'vi', '7': 'vii', '8': 'viii', '9': 'ix', '10': 'x'}
TWINS = {**ROMAN, **{roman: digit for digit, roman in ROMAN.items()}}
PREFIX_MATCHES = 300  # tokens a half-typed last word may stand for


def stem(word):
    """A light plural fold, the same for queries and titles: "wars" -> "war", "comedies" -> "comedy"."""
    if len(word) > 4 and word.endswith('ies'):
        return word[:-3] + 'y'
    if len(word) > 3 and word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
        return word[:-1]
    return word


def tokens(text):
    return [stem(word) for word in normalize(text).split()]


def _phrase(words, phrase):
    """Index where the token list `phrase` starts in `words`, or -1."""
    n = len(phrase)
    return next((i for i in range(len(words) - n + 1) if words[i:i + n] == phrase), -1)


@dataclass(frozen=True)
class Query:
    """What a search asks for: hard filters, and the words left to match."""
    text: str = ''
    words: tuple = ()
    genres: tuple = ()
    moods: tuple = ()
    kind: str | None = None
    years: tuple | None = None
    max_minutes: int | None = None
    notes: tuple = field(default=(), compare=False)

    def keeps(self, item):
        if self.kind and (item.kind == 'episode') != (self.kind == 'episode'):
            return False
        if self.years and not self.years[0] <= item.year <= self.years[1]:
            return False
        if self.max_minutes and item.minutes > self.max_minutes:
            return False
        return all(g in item.genres for g in self.genres) and all(m in item.moods for m in self.moods)

    @property
    def filtered(self):
        return bool(self.genres or self.moods or self.kind or self.years or self.max_minutes)

    def labels(self):
        """Plain-language chips for what was understood: ["Comedy", "1990s", "Films"]."""
        out = [g.replace('-and-', ' & ').replace('-', ' ').capitalize() for g in self.genres]
        out += [m.capitalize() for m in self.moods]
        if self.years:
            lo, hi = self.years
            out.append(f'{lo}s' if hi == lo + 9 and lo % 10 == 0 else str(lo) if lo == hi
                       else f'before {hi + 1}' if lo <= 1800 else f'since {lo}')
        if self.max_minutes:
            out.append(f'up to {self.max_minutes} min')
        if self.kind:
            out.append('Podcasts' if self.kind == 'episode' else 'Films')
        return out


class TitleIndex:
    """Titles by ID, the genre vocabulary, and search in relevance order (see the module docstring)."""

    def __init__(self, catalog, popularity=None):
        self.items = list(catalog)
        self.by_id = {item.id: item for item in self.items}
        self.position = {item.id: index for index, item in enumerate(self.items)}
        self.genres = sorted({genre for item in self.items for genre in item.genres})
        self.likes = [math.log1p((popularity or {}).get(item.id, 0)) for item in self.items]
        self.titles = [normalize(item.title) for item in self.items]
        self.compact = [title.replace(' ', '') for title in self.titles]
        self.title_words = [frozenset(tokens(item.title)) for item in self.items]
        self.meta_words = [frozenset(tokens(' '.join([item.series or '', *item.genres, *item.tags]).replace('-', ' ')))
                           for item in self.items]
        self.postings = {}  # token -> indexes of titles whose text contains it
        for index, item in enumerate(self.items):
            text = ' '.join([item.title, str(item.year), item.series or '', ' '.join(item.genres).replace('-', ' '),
                             ' '.join(item.tags), item.description])
            for token in set(tokens(text)):
                self.postings.setdefault(token, set()).add(index)
        self.vocabulary = sorted(self.postings)
        self.by_popularity = sorted(range(len(self.items)), key=lambda i: (-self.likes[i], i))

    def __len__(self):
        return len(self.items)

    # ---------- understanding ----------

    def understand(self, text):
        clean = normalize(text)
        words = [stem(w) for w in clean.split()]
        filter_word = clean in GENRE_WORDS or clean in MOOD_WORDS or clean in KIND_WORDS or clean in DECADE_WORDS
        if len(clean) >= 3 and not filter_word and any(clean in title for title in self.titles):
            return Query(text, tuple(w for w in words if w not in STOP_WORDS) or tuple(words))
        raw, genres, moods, kind, years, max_minutes = clean.split(), [], [], None, None, None
        used = [False] * len(raw)

        def take(phrase):
            parts = phrase.split()
            at = _phrase(raw, parts)
            if at < 0 or any(used[at:at + len(parts)]):
                return False
            used[at:at + len(parts)] = [True] * len(parts)
            return True

        for phrase in sorted(GENRE_WORDS, key=lambda p: -len(p.split())):  # longest first: "science fiction"
            if all(g in self.genres for g in GENRE_WORDS[phrase]) and take(phrase):
                genres += [g for g in GENRE_WORDS[phrase] if g not in genres]
        for phrase in sorted(MOOD_WORDS, key=lambda p: -len(p.split())):
            if take(phrase) and MOOD_WORDS[phrase] not in moods:
                moods.append(MOOD_WORDS[phrase])
        for i, word in enumerate(raw):
            if used[i]:
                continue
            if word in KIND_WORDS:
                kind, used[i] = KIND_WORDS[word], True
            elif word in DECADE_WORDS:
                years, used[i] = (DECADE_WORDS[word], DECADE_WORDS[word] + 9), True
            elif decade := re.fullmatch(r'(?:(19|20)?(\d))0s', word):
                century = int(decade[1]) * 100 if decade[1] else (2000 if decade[2] in '01' else 1900)
                start = century + int(decade[2]) * 10
                years, used[i] = (start, start + 9), True
            elif re.fullmatch(r'(18|19|20)\d\d', word):
                year = int(word)
                before = i > 0 and raw[i - 1] in ('before', 'pre')
                after = i > 0 and raw[i - 1] in ('after', 'since')
                years = (0, year - 1) if before else (year if raw[i - 1] == 'since' else year + 1, 9999) if after \
                    else (year, year)
                used[i] = True
                if before or after:
                    used[i - 1] = True
        # "under 90 minutes" excludes 90; "90 minutes", "for 2 hours" or "at most 90 minutes" include it.
        length = re.search(r'\b(?:(under|less than|shorter than|no longer than|at most|max|within|for|in) )?'
                           r'(\d+) ?(minutes?|mins?|m|hours?|hrs?|h)\b', clean)
        if length:
            minutes = int(length[2]) * (60 if length[3].startswith('h') else 1)
            max_minutes = minutes - 1 if length[1] in ('under', 'less than', 'shorter than') else minutes
            start = len(clean[:length.start()].split())  # the phrase's first word
            used[start:start + len(length[0].split())] = [True] * len(length[0].split())
        left = [stem(w) for w, done in zip(raw, used, strict=True)
                if not done and w not in STOP_WORDS and stem(w) not in STOP_WORDS]
        return Query(text, tuple(left), tuple(genres), tuple(moods), kind, years, max_minutes)

    def _spread_shows(self, order):
        """Each show's first episode before any show's second, keeping the order otherwise (films are unaffected)."""
        seen = Counter()
        rounds = []
        for i in order:
            series = self.items[i].series
            rounds.append(seen[series] if series else 0)
            if series:
                seen[series] += 1
        return [i for _, i in sorted(zip(rounds, order, strict=True), key=lambda pair: pair[0])]

    # ---------- matching ----------

    def _matches(self, word, last):
        found = set(self.postings.get(word, ()))
        if word in TWINS:
            found |= self.postings.get(TWINS[word], set())
        if last and not found and len(word) >= 2:  # still being typed: "star wa"
            start = bisect_left(self.vocabulary, word)
            for token in self.vocabulary[start:start + PREFIX_MATCHES]:
                if not token.startswith(word):
                    break
                found |= self.postings[token]
        return found

    def _score(self, index, query, phrase):
        title, score = self.titles[index], 0.0
        if phrase:
            score += 100 if title == phrase else 50 if title.startswith(phrase) else 25 if phrase in title else 0
        for word in query.words:
            alternatives = {word, TWINS.get(word, word)}
            if alternatives & self.title_words[index]:
                score += 12
            elif alternatives & self.meta_words[index]:
                score += 5
            else:
                score += 2
        return score + 3 * self.likes[index]

    def search(self, query='', keep=None, offset=0, limit=48):
        """(page of titles, total matches, the Query understood)."""
        understood = query if isinstance(query, Query) else self.understand(query)

        def allowed(i):
            return understood.keeps(self.items[i]) and (keep is None or keep(self.items[i]))

        words = understood.words
        if not words:
            order = self._spread_shows([i for i in self.by_popularity if allowed(i)])
            return [self.items[i] for i in order[offset:offset + limit]], len(order), understood
        sets = [self._matches(word, last=n == len(words) - 1) for n, word in enumerate(words)]
        hits = set.intersection(*sets)
        compact = ''.join(words)
        if not hits and len(compact) >= 4:  # "starwars": the words run together in a title
            hits = {i for i, title in enumerate(self.compact) if compact in title}
        if not hits and len(sets) >= 2:  # a long request: titles matching most of its words
            counts = Counter(i for found in sets for i in found)
            best = max(counts.values(), default=0)
            hits = {i for i, n in counts.items() if n == best and n >= math.ceil(len(sets) / 2)}
        phrase = normalize(understood.text) if not understood.filtered else ''
        ranked = sorted((i for i in hits if allowed(i)), key=lambda i: (-self._score(i, understood, phrase), i))
        return [self.items[i] for i in ranked[offset:offset + limit]], len(ranked), understood
