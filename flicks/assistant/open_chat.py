"""The corner chat with a language model: one message in, one tool chosen, an answer from what the tool found.

The model plans with one constrained JSON reply (find, similar, about, previous or help), Flicks runs that
plan against the catalogue and the recommender, and the model then answers in a few sentences from the
results only. Flicks' own readers overrule the plan where they are reliable and small models are not:
lengths, decades, films or series, and genres to avoid. The cards the viewer sees are always the tool's
results, so they are real catalogue titles; a sentence of the answer that names any other title is held
back, and the answer streams one checked sentence at a time, so nothing shown is later taken back.
docs/adr/0019-title-chat.md.
"""
from bisect import bisect_left
from dataclasses import asdict, replace
from datetime import date
import json
import re

from ..core import MOODS
from ..search import tokens
from ..text import normalize
from .llm import LLMError

RESULTS = 5
HISTORY = 5           # earlier lines of the conversation the planner sees, for follow-ups
MAX_DESCRIPTION = 600  # per title when the answer needs full details

PLAN = """You plan for Flicks, a film and TV app with a catalogue of titles. Read the conversation and choose ONE
action for the viewer's LAST message. Reply with JSON only.
- "find": titles to watch. "query" = specific words to look for in titles and descriptions: a person (full name,
  "Robert Downey Jr." for RDJ), franchise, studio, character, place or topic (heist, space, Paris, Pixar).
  Leave "query" empty when the viewer only gives a mood, a genre, a length or things to avoid.
- "similar": titles like one the viewer names, or what to watch after it. "title" = that title.
- "about": a question about one title (cast, length, plot, is it scary, is it OK for kids). "title" = that title.
- "previous": a question about the titles Flicks just showed ("which of those is shortest?", "the first one").
- "help": greetings, questions about Flicks, anything not about choosing or knowing a title.
Filters (only what the viewer said): "genres", "avoid_genres" (from: {genres}), "mood" (from: {moods}),
"max_minutes", "decade" (e.g. 1980), "kind" ("film" or "series").
Examples:
"Do we have any RDJ movies?" -> {"action":"find","query":"Robert Downey Jr.","kind":"film"}
"a heist movie" -> {"action":"find","query":"heist","kind":"film"}
"Pixar" -> {"action":"find","query":"Pixar"}
"a horror movie from the 80s" -> {"action":"find","genres":["horror"],"decade":1980,"kind":"film"}
"a documentary about space" -> {"action":"find","query":"space","genres":["documentary"]}
"cozy and funny, about 90 minutes" -> {"action":"find","mood":"relaxing","genres":["comedy"],"max_minutes":90}
"no horror, something light" -> {"action":"find","mood":"uplifting","avoid_genres":["horror"]}
"something for kids" -> {"action":"find","genres":["family"]}
"Iron Man" -> {"action":"similar","title":"Iron Man"}
"what should I watch after Arrival?" -> {"action":"similar","title":"Arrival"}
"something like Toy Story but for adults" -> {"action":"similar","title":"Toy Story","avoid_genres":["family","animation"]}
"How long is The Godfather?" -> {"action":"about","title":"The Godfather"}
"Is Toy Story OK for kids?" -> {"action":"about","title":"Toy Story"}
"What can you do?" -> {"action":"help"}
After Flicks showed titles, "which of those is the shortest?" -> {"action":"previous"}
After "Viewer: a heist movie", "something more recent" -> {"action":"find","query":"heist","decade":2010}"""

ANSWER = """You are Flicks, a warm, brief film assistant, talking to the viewer as "you". The titles in RESULTS are
shown to the viewer as cards under your reply. Reply to the viewer's message in one to three short sentences
(at most 40 words, no lists) using only RESULTS: say what you found and why it fits, naming at most three titles
exactly as written in RESULTS. "matched" says where a title matched the viewer's words. If RESULTS are empty or
do not answer the question, say so honestly. Never invent cast, directors, years, ratings or plot. Plain text only."""

HELP = ('I find films and series in your Flicks catalogue, on this computer. Try a mood (something cozy for 90 '
        'minutes), a person (Tom Hanks films), a topic (a heist movie), titles like one you love, or a question '
        'about a title (is Alien scary?).')
NOTHING = 'I could not find anything for that. Try other words.'
FOUND = 'Here is what I found.'

NUMBER = re.compile(r'\d')
TIME_WORDS = re.compile(r'\d|hour|minute|\bmins?\b|short|quick|long')
KIND_WORDS = re.compile(r'\b(film|films|movie|movies|series|show|shows|tv|sitcoms?)\b')
RECENT = re.compile(r'\b(recent|newer|new|latest|modern)\b')
SPOKEN = [(re.compile(r'half an hour'), 30), (re.compile(r'hour and a half'), 90),
          (re.compile(r'\b(an|one) hour\b'), 60), (re.compile(r'\btwo hours\b'), 120), (re.compile(r'\bthree hours\b'), 180)]
SENTENCE = re.compile(r'(?<=[.!?…])\s+|(?<=[.!?…]["”’)])\s+')  # the closing quote stays with its sentence
LIST_MARK = re.compile(r'(^|\s)(?:\d[.)]|[*•])\s')  # "1. " or "* " in the middle of a line
QUOTED = re.compile(r'["“*]([A-Z][^"”*]{2,80})["”*]')


def spoken_minutes(text):
    """Lengths said in words, which the search reader leaves to digits ("an hour and a half": 90)."""
    for pattern, minutes in SPOKEN:
        if pattern.search(text):
            return minutes
    return None


def plain(sentence):
    """A sentence without the markdown small models add anyway (bold, bullets, numbered items in a line)."""
    sentence = re.sub(r'\*\*|__|^#+\s*', '', sentence)
    sentence = re.sub(r'(?:^|\s)(?:[*•]|\d+[.)])(?=\s|$)', ' ', sentence)
    return ' '.join(sentence.split())


class OpenChat:
    def __init__(self, concierge):
        self.concierge, self.chat, self.checker = concierge, concierge.chat, concierge.checker
        self.titles, self.similar, self.recommender = concierge.titles, concierge.similar, concierge.recommender
        self.genres = list(self.titles.genres)
        self.system = PLAN.replace('{genres}', ', '.join(self.genres)).replace('{moods}', ', '.join(MOODS[1:]))
        self.schema = {'type': 'object', 'required': ['action'], 'properties': {
            'action': {'type': 'string', 'enum': ['find', 'similar', 'about', 'previous', 'help']},
            'query': {'type': 'string'}, 'title': {'type': 'string'},
            'genres': {'type': 'array', 'items': {'type': 'string', 'enum': self.genres}},
            'avoid_genres': {'type': 'array', 'items': {'type': 'string', 'enum': self.genres}},
            'mood': {'type': 'string', 'enum': list(MOODS[1:])}, 'max_minutes': {'type': 'integer'},
            'decade': {'type': 'integer'}, 'kind': {'type': 'string', 'enum': ['film', 'series']}}}
        self.by_title = {}
        for item in self.titles.items:
            self.by_title.setdefault(normalize(item.title), []).append(item)
        rules = concierge.interpreter
        while hasattr(rules, 'inner'):  # the deterministic rules at the bottom: no model, no student guesses
            rules = rules.inner
        self.rules = rules

    # ---------- planning ----------
    def plan(self, messages):
        """The model's plan for the last message (raises LLMError), with the filters Flicks reads itself."""
        lines = [f'{"Viewer" if m["role"] == "user" else "Flicks"}: {" ".join(str(m["text"]).split())[:200]}'
                 for m in messages[-HISTORY:]]
        prompt = [{'role': 'system', 'content': self.system},
                  {'role': 'user', 'content': '\n'.join(lines) + '\n\nJSON for the last viewer message:'}]
        reply = self.chat.complete(prompt, json_mode=True, schema=self.schema, max_tokens=100, wait=2)
        try:
            plan = json.loads(reply[reply.index('{'):reply.rindex('}') + 1])
        except ValueError:
            plan = None
        if not isinstance(plan, dict) or plan.get('action') not in self.schema['properties']['action']['enum']:
            raise LLMError('The model gave no plan')
        return self.overrule(plan, next(m['text'] for m in reversed(messages) if m['role'] == 'user'))

    def overrule(self, plan, said):
        """Drop filters the viewer did not say (small models fill optional fields), and set what Flicks' own
        readers read reliably: lengths, decades, films or series, genres to avoid."""
        plan = {k: v for k, v in plan.items() if v not in (None, '', [])}
        text = said.lower()
        understood = self.titles.understand(said)
        try:
            rules = self.rules.parse(said)
        except ValueError:
            rules = {}
        decade = plan.pop('decade', None)
        if understood.years:
            plan['years'] = list(understood.years)
        elif isinstance(decade, int) and 1880 <= decade <= 2030 and NUMBER.search(text):
            plan['years'] = [decade, decade + 9]
        elif RECENT.search(text):
            plan['years'] = [date.today().year - 15, date.today().year]  # "something more recent"
        if not TIME_WORDS.search(text):
            plan.pop('max_minutes', None)
        if not KIND_WORDS.search(text):
            plan.pop('kind', None)
        minutes = spoken_minutes(text) or understood.max_minutes
        if minutes:
            plan['max_minutes'] = minutes
        if understood.kind in ('films', 'series'):
            plan['kind'] = 'film' if understood.kind == 'films' else 'series'
        avoid = {g for g in plan.get('avoid_genres', []) if g in self.genres}
        avoid |= set((rules.get('patch') or {}).get('excluded_genres', []))
        plan['avoid_genres'] = sorted(avoid)
        wanted = [g for g in plan.get('genres', []) if g in self.genres]
        if plan['action'] == 'find':
            wanted += understood.genres
        plan['genres'] = [g for g in dict.fromkeys(wanted) if g not in avoid]
        if plan.get('mood') not in MOODS:
            plan.pop('mood', None)
        if not isinstance(plan.get('max_minutes'), int) or not 10 <= plan['max_minutes'] <= 600:
            plan.pop('max_minutes', None)
        return {k: v for k, v in plan.items() if v not in (None, '', [])}

    def labels(self, plan, anchor=None):
        """Chips for what Flicks understood."""
        wish = self.wish(plan)
        wish.like = anchor
        query = plan.get('query') if plan['action'] == 'find' else None
        return ([f'“{query}”'] if query else []) + wish.labels()

    def wish(self, plan):
        from .concierge import Wish
        patch = {k: plan[k] for k in ('mood',) if k in plan}
        if 'max_minutes' in plan:
            patch['minutes'] = plan['max_minutes']
        if plan.get('avoid_genres'):
            patch['excluded_genres'] = plan['avoid_genres']
        if plan.get('kind') in ('film', 'series'):
            patch['kind'] = 'films' if plan['kind'] == 'film' else 'series'
        return Wish(patch=patch, genres=list(plan.get('genres', [])), years=tuple(plan['years']) if 'years' in plan else None)

    # ---------- tools ----------
    def keep(self, plan, shown=()):
        genres, avoid = plan.get('genres', []), plan.get('avoid_genres', [])
        kind, cap = plan.get('kind'), plan.get('max_minutes')
        years = self.wish(plan).years

        def keep(item):
            return (item.id not in shown and all(g in item.genres for g in genres)
                    and not any(g in item.genres for g in avoid)
                    and (kind not in ('film', 'series') or item.is_series == (kind == 'series'))
                    and (not years or years[0] <= item.year <= years[1]) and (not cap or item.minutes <= cap))
        return keep

    def lookup(self, title, order):
        """The catalogue title the model named: an exact name (the best known, if several share it), else search."""
        if not isinstance(title, str) or not title.strip():
            return None
        candidates = self.by_title.get(normalize(title))
        if not candidates:  # a near name ("Amelie"), but every word must be in the title: not "The Iron Giant"
            words = tokens(title)
            page, _, _ = self.titles.search(title, None, 0, 20)
            candidates = [item for item in page
                          if all(any(t.startswith(w) for t in tokens(item.title)) for w in words)]
        return min(candidates, key=lambda item: order.get(item.id, len(order))) if candidates else None

    def search(self, query, keep, order):
        """Titles whose own words include every word of the query: the title itself first, then Flicks' ranking."""
        sets = [self.postings(word) for word in tokens(query)]
        found = set.intersection(*sets) if sets else set()
        if not found:  # no exact words (a misspelling, a run-together name): the app's own fuzzy search
            page, _, _ = self.titles.search(query, keep, 0, 50)
            return page
        q = normalize(query)
        items = [self.titles.items[i] for i in found if keep(self.titles.items[i])]
        return sorted(items, key=lambda item: (0 if normalize(item.title) == q else 1 if q in normalize(item.title) else 2,
                                               order.get(item.id, len(order))))

    def postings(self, word):
        """Titles with the word, or a longer word it starts ("paris": Parisian), in their own text."""
        vocabulary, found = self.titles.vocabulary, set()
        for n in range(bisect_left(vocabulary, word), len(vocabulary)):
            if not vocabulary[n].startswith(word) or (len(word) < 4 and vocabulary[n] != word):
                break
            found |= self.titles.postings[vocabulary[n]]
        return found

    def run(self, plan, feedback, base, shown, previous):
        """(note for the model, picks, every title the tool matched, session for Home or None, the title named)."""
        action, query = plan['action'], plan.get('query', '').strip()
        if action == 'find' and not query:  # a mood, a length, genres: the recommender's picks for tonight
            session, picks, matched = self.concierge.recommend(feedback, base, self.wish(plan), shown)
            note = 'Personal picks for tonight.' if matched else 'Nothing matched everything; these are the closest.'
            return note, picks, set(), session, None
        scores = self.recommender.taste.scores(feedback)
        everything = replace(base, minutes=600, kind='any', excluded_genres=[], playable=False)
        rows = {row[1]: row for row in self.recommender.rank(feedback, everything, scores=scores)}
        order = {key: n for n, key in enumerate(rows)}
        anchor, matched = None, set()
        if action == 'previous':
            items = [self.titles.by_id[i] for i in previous if i in self.titles.by_id]
            note = 'The titles shown in the last reply, with full details.'
        elif action == 'about':
            anchor = self.lookup(plan.get('title'), order)
            items = [anchor] if anchor else []
            note = 'The title asked about.' if anchor else 'That title is not in the catalogue.'
        elif action == 'similar':
            anchor = self.lookup(plan.get('title'), order)
            near = self.similar.scores({anchor.id: 1}) if anchor else {}
            ranked = [self.titles.by_id[k] for k in sorted(near, key=lambda k: -near[k]['taste'])
                      if k != anchor.id and k in self.titles.by_id]
            keep, unseen = self.keep(plan), self.keep(plan, shown)
            items = [i for i in ranked if unseen(i)][:RESULTS] or [i for i in ranked if keep(i)][:RESULTS]
            note = (f'Flicks has {anchor.title} ({anchor.year}). These are the titles most like it.' if anchor
                    else 'That title is not in the catalogue.')
        else:
            hits = self.search(query, self.keep(plan, shown), order) or self.search(query, self.keep(plan), order)
            items, matched = hits[:RESULTS], {normalize(item.title) for item in hits}
            note = f'{len(hits)} titles match "{query}". The best known are first.'
        if anchor:
            matched.add(normalize(anchor.title))
        picks = self.recommender.picks(feedback, [rows[item.id] for item in items if item.id in rows], scores)
        return note, picks, matched, None, anchor if action == 'similar' else None

    # ---------- answering ----------
    def card(self, item, query='', full=False):
        out = {'title': item.title, 'year': item.year, 'kind': 'series' if item.is_series else 'film',
               'minutes per episode' if item.is_series else 'minutes': item.minutes, 'genres': item.genres[:4]}
        sentences = SENTENCE.split(item.description.strip())
        if full:
            out.update(description=item.description[:MAX_DESCRIPTION], tags=item.tags[:8], moods=item.moods)
            return out
        out['about'] = sentences[0][:200]
        words = set(tokens(query))
        hit = next((s for s in sentences if words & set(tokens(s))), None) if words else None
        if hit and hit != sentences[0]:
            out['matched'] = hit[:220]  # why it matched: often the sentence that names the person
        return out

    def answer(self, said, plan, note, items, allowed):
        """Yield checked sentences of the model's answer as they finish."""
        full = plan['action'] in ('about', 'previous')
        results = {'note': note, 'titles': [self.card(item, plan.get('query', ''), full) for item in items]}
        prompt = [{'role': 'system', 'content': ANSWER},
                  {'role': 'user', 'content': f'RESULTS:\n{json.dumps(results, ensure_ascii=False)}\n\nViewer: {said}'}]
        stream = getattr(self.chat, 'stream', None)
        pieces = stream(prompt, max_tokens=90, wait=2) if stream else [self.chat.complete(prompt, max_tokens=90, wait=2)]
        buffer = ''
        for piece in pieces:
            buffer = LIST_MARK.sub(r'\1', buffer + piece)
            *finished, buffer = SENTENCE.split(buffer)
            for sentence in finished:
                if self.grounded(sentence, allowed) and len(plain(sentence)) > 3:
                    yield plain(sentence)
        # The token limit can stop the model mid-sentence: only a finished last sentence is kept.
        if re.search(r'[.!?…]["”’)]*\s*$', buffer) and self.grounded(buffer, allowed) and len(plain(buffer)) > 3:
            yield plain(buffer)

    def grounded(self, sentence, allowed):
        """A sentence may name only allowed titles: the results, what the tool matched, what the viewer said."""
        if '{' in sentence or 'RESULTS' in sentence:  # the prompt echoed back
            return False
        named = {title for title in self.checker.named_titles(sentence) if ' ' in title}
        named |= {normalize(span) for span in QUOTED.findall(sentence) if ' ' in span.strip()}
        return all(title in allowed or any(title in a or a in title for a in allowed if len(a) > 3) for title in named)

    # ---------- the conversation ----------
    def converse(self, feedback, base, messages, shown=(), previous=()):
        """Yield events: {"understood"}, maybe {"picks"}, {"delta"}s, then {"done"}. Raises LLMError when the
        model cannot plan, before anything is yielded, so the caller can fall back to the form."""
        plan = self.plan(messages)
        said = next(m['text'] for m in reversed(messages) if m['role'] == 'user')
        if plan['action'] == 'help':
            yield {'understood': [], 'patch': {}}
            yield {'delta': HELP}
            yield {'done': True, 'step': 'help', 'text': HELP, 'model': False}
            return
        note, picks, matched, session, anchor = self.run(plan, feedback, base, set(shown), list(previous))
        items = [self.titles.by_id[pick['content']['id']] for pick in picks]
        yield {'understood': self.labels(plan, anchor), 'patch': self.wish(plan).patch if session else {}}
        if picks:
            yield {'picks': picks, **({'session': asdict(session)} if session else {})}
        viewer = set()
        for m in messages:
            if m['role'] == 'user':
                viewer |= self.checker.named_titles(str(m['text']))
        allowed = {normalize(item.title) for item in items} | matched | viewer
        sentences = []
        try:
            for sentence in self.answer(said, plan, note, items, allowed):
                yield {'delta': (' ' if sentences else '') + sentence}
                sentences.append(sentence)
        except LLMError:
            pass  # what was said stands; the cards are already there
        if not sentences:
            fallback = FOUND if items else NOTHING
            yield {'delta': fallback}
            sentences = [fallback]
        yield {'done': True, 'step': 'picks' if items else 'answer', 'text': ' '.join(sentences), 'model': True}
