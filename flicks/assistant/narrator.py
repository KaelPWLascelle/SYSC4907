"""Plain-language explanations of a pick, written by the local language model from the pick's own factors.

The ranking is already explained exactly by its factors (they add up to the score); the narrator only
rewords them. It is grounded and checked: the model sees the facts below and nothing about the user
beyond them, and a reply that names a catalogue title that is not in those facts, links somewhere, or
runs long is discarded, so the interface keeps its template reasons. Replies are cached per profile and
facts, so reopening a title costs nothing. docs/adr/0013-local-llm.md.
"""
from collections import OrderedDict
import json
import re
import threading

from ..text import normalize
from .llm import LLMError

SYSTEM = ('You explain a film recommendation to the viewer in one or two short sentences '
          '(at most 45 words), speaking to them as "you". Use only the facts given; describe the story only '
          'with the "about" fact. Do not invent plot details, actors, awards, quotes, or other titles. Do not '
          'mention scores or percentages. '
          'Plain text only: no lists, markdown, or links.')
# A narration is optional: if the model is busy (another narration, or the agent), skip it rather than queue.
WAIT_SECONDS = 2
FACTOR_WORDS = {'taste': 'matches your ratings', 'mood': 'fits the mood you asked for',
                'intensity': 'matches the intensity you asked for', 'novelty': 'matches how familiar or new you want it'}
CONNECTORS = {'of', 'the', 'a', 'an', 'and', 'in', 'to', 'on', 'at', 'for', 'from', 'with', 'vs', '&'}
CAPITALIZED_RUN = re.compile(r"[A-Z0-9][\w'’:-]*(?:\s+(?:[A-Z0-9][\w'’:-]*|" + '|'.join(sorted(CONNECTORS)) + r"))*")


def facts(pick, session):
    """What the model may say, taken from a pick returned by Recommender (and nothing else)."""
    content, factors = pick['content'], pick['factors']
    strongest = sorted(factors, key=lambda k: -factors[k])[:2]
    scene = {'mood': session.mood, 'minutes available': session.minutes}
    return {
        'title': content['title'], 'year': content['year'], 'kind': content['kind'], 'minutes': content['minutes'],
        'genres': content['genres'][:4], 'moods': content['moods'][:3],
        # The catalogue's own first sentence, so anything said about the story is grounded in it.
        'about': _first_sentence(content['description']),
        'because you liked': pick.get('because', [])[:2],
        'themes shared with what you liked': pick.get('evidence', [])[:4],
        'crowd favourite while you rate more': bool(pick.get('popular')),
        # While the popularity prior supplies the taste score, "matches your ratings" would not be true.
        'main reasons': [('is widely liked, while Flicks is still learning your taste' if k == 'taste' and pick.get('popular')
                          else FACTOR_WORDS[k]) for k in strongest if k in FACTOR_WORDS],
        'your scene': scene,
    }


def _first_sentence(text, limit=220):
    sentence = re.split(r'(?<=[.!?])\s', text.strip(), maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[:limit].rsplit(' ', 1)[0] + '…'


class Narrator:
    def __init__(self, chat, catalog, cache_size=256):
        self.chat, self.cache, self.cache_size, self.lock = chat, OrderedDict(), cache_size, threading.Lock()
        # Normalised title -> displayed title, for spotting titles the model was not given.
        self.titles = {normalize(item.title): item.title for item in catalog if len(normalize(item.title)) >= 3}

    def narrate(self, profile_id, pick, session):
        """{"text", "model"} or raises LLMError; the caller falls back to the template reasons."""
        given = facts(pick, session)
        key = (profile_id, json.dumps(given, sort_keys=True))
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
        reply = self.chat.complete([{'role': 'system', 'content': SYSTEM},
                                    {'role': 'user', 'content': 'Facts:\n' + json.dumps(given, indent=1)}],
                                   max_tokens=120, wait=WAIT_SECONDS)
        text = self.check(reply, given)
        result = {'text': text, 'model': self.chat.model}
        with self.lock:
            self.cache[key] = result
            while len(self.cache) > self.cache_size:
                self.cache.popitem(last=False)
        return result

    def check(self, reply, given):
        text = ' '.join(reply.replace('*', '').replace('_', ' ').split())
        if not 15 <= len(text) <= 360:
            raise LLMError('The model reply was empty or too long')
        if re.search(r'https?://|www\.|\d+\s*%', text):
            raise LLMError('The model reply contained a link or a percentage')
        allowed = {normalize(t) for t in [given['title'], *given['because you liked']]}
        for title in self.named_titles(text):
            if title not in allowed:
                raise LLMError(f'The model named a title it was not given: {self.titles[title]}')
        return text

    def named_titles(self, text):
        """Catalogue titles written as proper names in `text` (capitalised runs, quoted spans), normalised."""
        found = set()
        spans = [m.group(0) for m in CAPITALIZED_RUN.finditer(text)]
        spans += re.findall('["\u201c]([^"\u201d]{3,80})["\u201d]', text)  # double-quoted spans
        for span in spans:
            # Longest match first, left to right, so a title's own words ("Empire" in "The Empire Strikes
            # Back") are not read as another title.
            words, start = normalize(span).split(), 0
            while start < len(words):
                for end in range(len(words), start, -1):
                    candidate = ' '.join(words[start:end])
                    if candidate in self.titles and (end - start > 1 or self._mid_sentence(text, candidate)):
                        found.add(candidate)
                        start = end
                        break
                else:
                    start += 1
        return found

    @staticmethod
    def _mid_sentence(text, word):
        """A one-word title counts only when capitalised mid-sentence ("unlike Alien"), not as a sentence's first word."""
        for match in re.finditer(rf'\b{re.escape(word)}\b', text, re.I):
            before = text[:match.start()].rstrip()
            if match.group(0)[0].isupper() and before and before[-1] not in '.!?':
                return True
        return False
