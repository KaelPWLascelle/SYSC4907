"""Bounded, transparent command interpretation. Parsing never changes stored state."""
import re
import unicodedata
from .core import MOODS, Session


def normalize(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', text.replace("'", '')).strip()


ONES = dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(), range(20)))
TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))


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


class CommandInterpreter:
    name = 'Local command rules'

    def __init__(self, catalog):
        self.catalog = catalog
        self.genres = sorted({g for c in catalog for g in c.genres})

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
        text = re.sub(r'^(?:hey )?(?:flicks|kevin)\b\s*', '', text)  # kevin: the project's former name
        text = re.sub(r'^please\s+|\s+please$', '', text)
        feedback = re.fullmatch(r'(?:i )?(like|liked|love|loved|dislike|disliked|hate|hated|did not like|didnt like|clear(?: my)? rating for|clear(?: my)? rating of) (.+)', text)
        if feedback:
            verb, title = feedback.groups()
            candidates = [c for c in self.catalog if normalize(c.title) == title]
            if len(candidates) != 1:
                return self.unknown('Use one exact catalogue title, for example “Like Arrival”. No rating changed.')
            value = 0 if verb.startswith('clear') else -1 if verb in ('dislike', 'disliked', 'hate', 'hated', 'did not like', 'didnt like') else 1
            item = candidates[0]
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
            return self.unknown('Try “relaxing, 90 minutes, low intensity”, “no horror”, or “Like Arrival”. I cannot play media or answer general questions yet.', 'unrecognized')
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
