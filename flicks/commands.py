"""Bounded, transparent command interpretation. Parsing never changes stored state.

Intents: `feedback` (rate a title), `session` (change the scene), `play` (a title), `search` (everyday
search, or titles like one), and `unknown`. Every one is shown to the user before it is applied.
"""
from dataclasses import asdict
import re
import unicodedata

from .core import MOODS, Session
from .search import GENRE_WORDS, TitleIndex


def normalize(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', text.replace("'", '')).strip()


ONES = dict(zip(['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'], range(20), strict=True))
TENS = dict(zip(['twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'], range(20, 100, 10), strict=True))


def number_words(text):
    """Normalize spoken integer quantities before unit parsing."""
    words = '|'.join((*ONES, *TENS, 'hundred'))
    pattern = rf'\b(?:{words})(?: (?:{words}|and))*\b'
    def convert(match):
        total = 0
        for word in match[0].split():
            if word == 'hundred': total *= 100
            else: total += ONES.get(word, TENS.get(word, 0))
        return str(total)
    return re.sub(pattern, convert, text)


HINT = 'Try “relaxing, 90 minutes”, “no horror”, “Like Arrival”, “play The General” or “funny films from the 90s”.'
PLAY = re.compile(r'(?:play|watch|start|put on|listen to|resume) (.+)')
SEARCH_VERBS = re.compile(r'(?:find|search(?: for)?|show me|look for|looking for|any) ')
NEGATED = re.compile(r'\b(?:no|without|avoid|exclude|not) \w+(?: \w+)?')
SIMILAR = re.compile(r'(?:show me |find |give me )?(?:more like|something like|similar to|titles like|films like|movies like|shows like) (.+)')


class CommandInterpreter:
    name = 'Local command rules'

    def __init__(self, catalog, titles: TitleIndex | None = None, playable=None):
        self.catalog = catalog
        self.titles = titles or TitleIndex(catalog)
        self.playable = playable or (lambda content_id: False)  # content ID -> can it be played here?
        self.genres = sorted({g for c in catalog for g in c.genres})

    def find_title(self, text, to_play=False):
        """The one title `text` names, or None. Never a guess between alternatives.

        An exact title wins, narrowed by a year ("the general 1926") and, when playing, by what can be
        played. Otherwise at least two words must all appear in exactly one title ("grand budapest"); one
        loose word ("toy") or a list ("Paddington or Paddington 2") is refused rather than resolved.
        """
        exact = self.same_name(text)
        if to_play and len(exact) > 1:
            exact = [c for c in exact if self.playable(c.id)] or exact
        if len(exact) == 1:
            return exact[0]
        if exact or re.search(r'\b(?:or|and)\b|,', text):
            return None  # several titles share the name, or several are named: ask rather than guess
        words = set(self.titles.understand(text).words)
        if len(words) < 2:
            return None
        named = [i for i, title in enumerate(self.titles.title_words) if words <= title]
        return self.titles.items[named[0]] if len(named) == 1 else None

    def same_name(self, text):
        """Titles called exactly `text`, or `text` without a trailing year and released that year."""
        named = re.fullmatch(r'(.+?) ((?:18|19|20)\d\d)', text)
        if named and (dated := [c for c in self.catalog if normalize(c.title) == named[1] and c.year == int(named[2])]):
            return dated
        return [c for c in self.catalog if normalize(c.title) == text]

    def not_found(self, text, verb):
        """Why `text` named no single title: several share the name, or none matched."""
        shared = self.same_name(text)
        if len(shared) > 1:
            years = ', '.join(str(c.year) for c in sorted(shared, key=lambda c: c.year))
            title = shared[0].title
            return self.unknown(f'Several titles are called “{title}” ({years}). Add the year, for example '
                                f'“{verb} {title} {shared[0].year}”.')
        return self.unknown(f'I could not find “{text}”. Try its exact title.')

    def genre_named(self, text):
        """The catalogue genre `text` names ("horror", "scary movies", "musicals"), or None."""
        words = re.sub(r'\b(?:movies?|films?|shows?|podcasts?)\b', '', text).strip()
        genres = GENRE_WORDS.get(words) or ((words,) if words in self.genres else ())
        return genres[0] if len(genres) == 1 and genres[0] in self.genres else None

    @staticmethod
    def unknown(message, reason='refused'):
        # reason 'refused': the rules recognised something and deliberately declined (negation,
        # conflicts, ambiguity). 'unrecognized': nothing matched, so a model fallback may try.
        return {'intent': 'unknown', 'summary': message, 'parser': 'rules', 'reason': reason}

    def parse(self, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise ValueError('Enter a command of 1–500 characters')
        if re.search(r'-\s*\d|\d[.,]\d|\bpoint\b', text.lower()):
            return self.unknown('Please use a positive whole-number time limit, such as 90 minutes.')
        text = normalize(text)
        text = re.sub(r'^(?:hey )?flicks\b\s*', '', text)
        text = re.sub(r'^please\s+|\s+please$', '', text)
        similar = SIMILAR.fullmatch(text)
        if similar:
            item = self.find_title(similar[1])
            if item is None:
                return self.not_found(similar[1], 'more like')
            return {'intent': 'search', 'similar': item.id, 'summary': f'Show titles like {item.title}',
                    'content': asdict(item), 'parser': 'rules'}
        play = PLAY.fullmatch(text)
        if play and re.search(r'\b(?:or|and)\b|,', play[1]):
            return self.unknown('Name one title to play, for example “play Arrival”.')
        if play and (item := self.find_title(play[1], to_play=True)):
            return {'intent': 'play', 'id': item.id, 'summary': f'Play {item.title}', 'content': asdict(item),
                    'parser': 'rules'}
        feedback = re.fullmatch(r'(?:i )?(like|liked|love|loved|dislike|disliked|hate|hated|did not like|didnt like|dont like|do not like|clear(?: my)? rating for|clear(?: my)? rating of) (.+)', text)
        if feedback:
            verb, title = feedback.groups()
            negative = verb in ('dislike', 'disliked', 'hate', 'hated', 'did not like', 'didnt like', 'dont like', 'do not like')
            genre = self.genre_named(title)
            if negative and genre and not any(normalize(c.title) == title for c in self.catalog):
                return {'intent': 'session', 'patch': {'excluded_genres': [genre]}, 'summary': f'Set avoid {genre}.',
                        'parser': 'rules', 'note': 'Genres you avoid are left out of your picks for this visit.'}
            item = self.find_title(title)
            if item is None:
                if len(self.same_name(title)) > 1:
                    return self.not_found(title, verb)
                return self.unknown('Use one exact catalogue title, for example “Like Arrival”. No rating changed.')
            value = 0 if verb.startswith('clear') else -1 if negative else 1
            return {'intent': 'feedback', 'id': item.id, 'value': value,
                    'summary': f'{ {1: "Like", -1: "Dislike", 0: "Clear rating for"}[value]} {item.title}', 'parser': 'rules'}

        patch = {}
        # Negation is not treated as a positive mood request.
        if re.search(r'\b(?:not|no|avoid|dont|do not) (?:very |too )?(?:relaxing|uplifting|curious|tense|reflective|intense|intensity|familiar|novel|new|under|less than)\b', text):
            return self.unknown('Please state the mood or intensity you want directly, such as “relaxing, low intensity”.')
        mood_hits = {m for m in MOODS[1:] if re.search(rf'\b{m}\b', text)}
        if re.search(r'\b(?:calm|chill)\b', text): mood_hits.add('relaxing')
        if re.search(r'\b(?:cheerful|feel good)\b', text): mood_hits.add('uplifting')
        if len(mood_hits) > 1:
            return self.unknown('Choose one mood per request so I do not guess between conflicting moods.')
        if mood_hits: patch['mood'] = mood_hits.pop()
        if re.search(r'\bany mood\b', text): patch['mood'] = 'any'
        numeric = number_words(text)
        numeric = re.sub(r'\b(?:an?|one|1) hour and a half\b', '90 minutes', numeric)
        numeric = re.sub(r'\bhalf an hour\b', '30 minutes', numeric)
        numeric = re.sub(r'\ban? hour\b', '1 hour', numeric)
        durations = list(re.finditer(r'\b(\d+)\s*(minutes?|mins?|hours?|hrs?)\b', numeric))
        if len(durations) > 1:
            return self.unknown('Give one time limit in minutes or hours, for example “90 minutes”.')
        if durations:
            match = durations[0]
            minutes = int(match[1])*(60 if match[2].startswith(('h',)) else 1)
            if re.search(r'\b(?:under|less than)\s*$', numeric[:match.start()]): minutes -= 1
            patch['minutes'] = minutes
        for field, pairs in {
            'intensity': [(r'\b(?:low intensity|easygoing|gentle)\b', .2), (r'\b(?:medium intensity|moderate intensity)\b', .5), (r'\b(?:high intensity|intense|full throttle)\b', .9)],
            'novelty': [(r'\b(?:familiar|comfort zone)\b', .1), (r'\b(?:surprise me|something new|new territory|adventurous)\b', .9)],
        }.items():
            hits = [value for pattern, value in pairs if re.search(pattern, text)]
            if len(hits) > 1:
                return self.unknown(f'Choose one {field} level per request.')
            if hits: patch[field] = hits[0]
        excluded = [g for g in self.genres if re.search(rf'\b(?:no|without|avoid|exclude) {re.escape(normalize(g))}\b', text)]
        if excluded: patch['excluded_genres'] = excluded
        if re.search(r'\b(?:allow all genres|clear exclusions)\b', text): patch['excluded_genres'] = []
        if not patch:
            if text in ('recommend something', 'find my next watch', 'show recommendations', 'recommendations'):
                return {'intent': 'session', 'patch': {}, 'summary': 'Refresh recommendations with the current session.', 'parser': 'rules'}
            if play and len(self.same_name(play[1])) > 1:
                return self.not_found(play[1], 'play')
            # "listen to something about Rome": not a title, so a search ("listen" asks for podcasts).
            return self.search(text) or self.unknown(f'Nothing matched. {HINT}', 'unrecognized')
        if self.wants_search(text) and (found := self.search(text)):
            # "scary movies under 90 minutes" describes what to find; the length becomes a search filter.
            return {**found, 'fallback': False}
        # Use the same domain validation as manual controls; no model can bypass it.
        Session(**patch)
        labels = []
        for key, value in patch.items():
            if key == 'excluded_genres': labels.append('avoid ' + ', '.join(value) if value else 'allow all genres')
            elif key == 'minutes': labels.append(f'time limit {value} minutes')
            elif key in ('intensity', 'novelty'): labels.append(f'{key} {round(value*100)}%')
            else: labels.append(f'{key}: {value}')
        return {'intent': 'session', 'patch': patch, 'summary': 'Set ' + '; '.join(labels) + '.',
                'parser': 'rules', 'note': 'Only the listed settings will change. Other wording is not interpreted.'}

    def wants_search(self, text):
        """True when a request describes what to find: a genre it does not negate, films or podcasts, a period, or "find…"."""
        wanted = self.titles.understand(NEGATED.sub(' ', text))
        return bool(SEARCH_VERBS.match(text) or wanted.genres or wanted.kind or wanted.years)

    def search(self, text):
        """A `search` command for an everyday request that matches titles, or None."""
        _, total, query = self.titles.search(text, limit=1)
        if not total:
            return None
        parts = query.labels() + [f'“{word}”' for word in query.words]
        # `fallback`: nothing more specific matched, so a local model may still read the request first.
        return {'intent': 'search', 'query': text, 'summary': 'Search for ' + (' · '.join(parts) or text),
                'parser': 'rules', 'fallback': True, 'note': f'{total:,} {"title matches" if total == 1 else "titles match"}.'}
