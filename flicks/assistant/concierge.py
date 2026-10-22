"""The concierge: a short conversation, opened from the corner of Home, that ends in three titles.

It asks at most two questions (what the viewer is in the mood for, then how much time they have) and
reads every answer with the readers Ask already uses: search's understanding of genres, moods, decades,
lengths and films-or-series; the rules; the Ask student; and "like <title>". The recommender then ranks
with what it learned, and the viewer gets three picks with their reasons. The local language model, when
one is configured, only words the questions and the pitch, from facts this module chose; a reply that
names a title it was not given falls back to Flicks' own sentence. Without a model the concierge still
works, in those sentences. Nothing is stored: the client sends the conversation each time.
docs/adr/0019-title-chat.md.
"""
from dataclasses import asdict, dataclass, field, replace
import json
import re

from ..core import MOODS, Session
from ..text import normalize
from .llm import LLMError

MAX_MESSAGES = 12
MAX_TEXT = 300
PICKS = 3
SIMILAR_POOL = 300  # "like Arrival": the viewer's ranking, kept to the titles most like it
SURPRISE = re.compile(r"\b(surprise me|anything|you pick|you choose|just pick|whatever|don'?t care|no idea|not sure|dunno)\b")
QUESTIONS = {
    'mood': 'What are you in the mood for? A feeling, a genre or a film you loved all work.',
    'time': 'How much time do you have tonight?',
}
VOICE = ('You are Flicks, a warm, brief film concierge inside a video player, talking to the viewer as "you". '
         'Plain text only, no lists or markdown.')
ASK = VOICE + (' Write one short, friendly question (at most 20 words) asking the viewer about {topic}. You may '
               'first acknowledge in a few words what they said. Do not name any film or series.')
PITCH = VOICE + (' In two or three short sentences (at most 60 words), offer the viewer these picks for tonight, '
                 'saying in a few words why each fits. Use only the facts given and name only these titles.')
TOPICS = {'mood': 'what they are in the mood for (a feeling, a genre, or a film they loved)',
          'time': 'how much time they have'}


@dataclass
class Wish:
    """What the conversation has said so far, as recommender settings and filters."""
    patch: dict = field(default_factory=dict)       # Session fields
    genres: list = field(default_factory=list)      # wanted genres (all must match, like search)
    years: tuple | None = None
    like: object = None                             # a catalogue item: "something like Arrival"
    surprise: bool = False

    @property
    def has_taste(self):
        return bool(self.genres or self.like or self.surprise
                    or {'mood', 'intensity', 'novelty', 'excluded_genres'} & self.patch.keys())

    @property
    def has_time(self):
        return 'minutes' in self.patch or self.surprise

    def labels(self):
        """Chips for what Flicks understood: ["Comedy", "Relaxing", "Up to 90 min"]."""
        out = [g.replace('-and-', ' & ').replace('-', ' ').capitalize() for g in self.genres]
        if self.patch.get('mood', 'any') != 'any':
            out.append(self.patch['mood'].capitalize())
        if 'intensity' in self.patch:
            out.append('Gentle' if self.patch['intensity'] < 0.35 else 'Intense' if self.patch['intensity'] > 0.65 else 'Balanced')
        if self.patch.get('novelty', 0) >= 0.8:
            out.append('Something new')
        if self.like is not None:
            out.append(f'Like {self.like.title}')
        if self.years:
            lo, hi = self.years
            out.append(f'{lo}s' if hi == lo + 9 and lo % 10 == 0 else f'{lo}–{hi}')
        out += [f'No {g.replace("-", " ")}' for g in self.patch.get('excluded_genres', [])]
        if 'minutes' in self.patch:
            out.append(f'Up to {self.patch["minutes"]} min')
        if self.patch.get('kind', 'any') != 'any':
            out.append(self.patch['kind'].capitalize())
        if self.surprise and len(out) == 0:
            out.append('Surprise me')
        return out


class Concierge:
    def __init__(self, recommender, titles, interpreter, similar, chat=None, checker=None):
        self.recommender, self.titles, self.interpreter, self.similar = recommender, titles, interpreter, similar
        self.chat, self.checker = chat, checker  # checker: narrator.Narrator, for spotting catalogue titles

    # ---------- reading ----------
    def read(self, texts):
        wish = Wish()
        for text in texts:
            self._read_one(wish, text)
        return wish

    def _read_one(self, wish, text):
        clean = normalize(text)
        if SURPRISE.search(clean):
            wish.surprise = True
        query = self.titles.understand(text)
        wish.genres = list(dict.fromkeys(wish.genres + list(query.genres)))
        if query.years:
            wish.years = query.years
        if query.max_minutes:
            wish.patch['minutes'] = max(1, min(600, query.max_minutes))
        if query.kind in ('films', 'series'):
            wish.patch['kind'] = query.kind
        if query.moods and query.moods[0] in MOODS:
            wish.patch['mood'] = query.moods[0]
        try:
            command = self.interpreter.parse(text)
            # What the rules alone read may change an earlier answer; the student's guesses only fill gaps,
            # so "about an hour and a half" cannot turn "cozy" into another mood.
            rules = getattr(self.interpreter, 'inner', self.interpreter).parse(text)
        except ValueError:
            return
        if command.get('similar'):
            wish.like = self.titles.by_id.get(command['similar'])
        for key, value in (rules.get('patch') or {}).items():
            if key == 'excluded_genres':
                wish.patch[key] = sorted(set(wish.patch.get(key, [])) | set(value))
            else:
                wish.patch[key] = value
        # The student reads the scene even when the rules took the words as a search ("cozy and funny").
        patch = getattr(self.interpreter, 'patch', None)
        if patch is not None:
            for key, value in patch(text).items():
                if key == 'excluded_genres':
                    wish.patch[key] = sorted(set(wish.patch.get(key, [])) | set(value))
                else:
                    wish.patch.setdefault(key, value)
        # A genre the viewer asked to avoid is never also a genre they want.
        wish.genres = [g for g in wish.genres if g not in wish.patch.get('excluded_genres', [])]

    # ---------- deciding ----------
    @staticmethod
    def next_step(wish, answers):
        """'mood', 'time' or 'picks'. At most two questions: after two answers, recommend anyway."""
        if not wish.has_taste and answers < 2:
            return 'mood'
        if not wish.has_time and answers < 2:
            return 'time'
        return 'picks'

    def recommend(self, feedback, base, wish, shown=()):
        session = replace(base, **{k: v for k, v in wish.patch.items() if k in Session.__dataclass_fields__})
        Session(**asdict(session))  # validates the merged settings
        scores = self.recommender.taste.scores(feedback)
        rows = [row for row in self.recommender.rank(feedback, session, scores=scores) if row[1] not in shown]
        if wish.like is not None:
            near = self.similar.scores({wish.like.id: 1})
            pool = set(sorted(near, key=lambda key: -near[key]['taste'])[:SIMILAR_POOL + 1]) - {wish.like.id}
            rows = [row for row in rows if row[1] in pool] or rows
        filtered = [row for row in rows if all(g in row[2].genres for g in wish.genres)
                    and (not wish.years or wish.years[0] <= row[2].year <= wish.years[1])]
        chosen = (filtered or rows)[:PICKS]
        return session, self.recommender.picks(feedback, chosen, scores), bool(filtered) or not (wish.genres or wish.years)

    # ---------- talking ----------
    def converse(self, feedback, base, messages, shown=()):
        """Yield events: {"understood"}, maybe {"picks"}, {"delta"}s, then {"done"}."""
        messages = list(messages)[-MAX_MESSAGES:]
        texts = [' '.join(str(m['text']).split())[:MAX_TEXT] for m in messages if m['role'] == 'user']
        texts = [t for t in texts if t]
        if not texts:
            raise ValueError('Say what you feel like watching')
        wish = self.read(texts)
        # Questions asked so far: answers to them are the user turns after the first assistant message.
        step = self.next_step(wish, len(texts))
        yield {'understood': wish.labels(), 'patch': wish.patch}
        if step != 'picks':
            fallback = QUESTIONS[step]
            facts = {'they said': texts[-1], 'understood so far': wish.labels()}
            yield from self._words(ASK.format(topic=TOPICS[step]), facts, fallback, step, allowed=set(), question=True)
            return
        session, picks, matched = self.recommend(feedback, base, wish, shown)
        if not picks:
            yield from self._done('Nothing fits all of that. Try more time, or fewer things to avoid.', 'picks', False)
            return
        yield {'picks': picks, 'session': asdict(session)}
        names = [p['content']['title'] for p in picks]
        lead = 'Here are three for tonight' if matched else 'Nothing matched everything, so here are the closest'
        fallback = f"{lead}: {', '.join(names[:-1])} and {names[-1]}." if len(names) > 1 else f'{lead}: {names[0]}.'
        facts = {'what the viewer wants': wish.labels() or ['anything good'],
                 'picks': [self._pick_facts(p) for p in picks]}
        yield from self._words(PITCH, facts, fallback, 'picks', allowed={normalize(n) for n in names})

    @staticmethod
    def _pick_facts(pick):
        content = pick['content']
        about = re.split(r'(?<=[.!?])\s', content['description'].strip(), maxsplit=1)[0][:220]
        return {'title': content['title'], 'year': content['year'], 'genres': content['genres'][:3],
                'minutes per episode' if content.get('series') else 'minutes': content['minutes'],
                'about': about, 'because you liked': pick.get('because', [])[:2],
                'shares with what you liked': pick.get('evidence', [])[:3]}

    def _words(self, system, facts, fallback, step, allowed, question=False):
        if self.chat is None:
            yield from self._done(fallback, step, False)
            return
        messages = [{'role': 'system', 'content': system + ' /no_think' * ('qwen3' in self.chat.model.lower())},
                    {'role': 'user', 'content': 'Facts:\n' + json.dumps(facts, indent=1)}]
        text = ''
        try:
            stream = getattr(self.chat, 'stream', None)
            pieces = stream(messages, max_tokens=50 if question else 120, wait=2) if stream else \
                [self.chat.complete(messages, max_tokens=50 if question else 120, wait=2)]
            for piece in pieces:
                text += piece
                yield {'delta': piece}
        except LLMError:
            yield from self._done(fallback, step, False)
            return
        text = ' '.join(text.split())
        if self._grounded(text, allowed, question):
            yield from self._done(text, step, True)
        else:
            yield from self._done(fallback, step, False)

    def _grounded(self, text, allowed, question):
        if not 8 <= len(text) <= (200 if question else 500) or re.search(r'https?://|www\.', text):
            return False
        if question and '?' not in text:
            return False
        if self.checker is None:
            return True
        quoted = {normalize(s) for s in re.findall('["“]([^"”]{2,80})["”]', text)}
        for title in self.checker.named_titles(text):
            if (' ' in title or title in quoted) and title not in allowed:
                return False
        return True

    @staticmethod
    def _done(text, step, worded):
        yield {'done': True, 'step': step, 'text': text, 'model': worded}
