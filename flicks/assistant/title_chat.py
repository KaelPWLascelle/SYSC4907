"""Questions about one title, answered by the local language model from the catalogue's own facts.

The viewer opens a title and asks ("Who's in it?", "Is it scary?", "Why this pick?"). The model sees that
title's catalogue entry, the recommender's reasons for it, and nothing else about the viewer. It never
ranks or changes anything. Replies stream word by word; a finished reply that names a catalogue title it
was not given, or links somewhere, is withdrawn and the viewer is told so. docs/adr/0019-title-chat.md.
"""
import json
import re

from ..text import normalize
from .llm import LLMError
from .narrator import FACTOR_WORDS, Narrator

SYSTEM = ("You are Flicks, a movie assistant inside a video player. Answer the viewer's question about the "
          "title below in one to three short sentences (at most 60 words), speaking to them as \"you\". Use only the facts given. "
          "If the facts do not contain the answer, say you don't know from the information Flicks has. "
          "Never guess people, music, age ratings, awards, reviews or plot details that are not in the facts. "
          "If asked to compare it with another title, say Flicks only has details about this one. "
          "Plain text only.")
MAX_QUESTION = 300
MAX_TURNS = 3          # earlier questions and answers kept for follow-ups ("and who else is in it?")
MAX_TOKENS = 120     # about 90 words: a cap, not a target (the prompt asks for 60)
UNKNOWN_RATING = 'not known to Flicks'
# "Suitable for all ages", "fine for kids", "kid-friendly", "not … inappropriate for children": a claim that
# a title is fine for children, which Flicks can't back without an age rating.
YOUNG = r"(kids?|children|child|all ages|famil(y|ies)|young (viewers|audiences|children)|everyone|all audiences|(a )?(wide|general) audiences?)"
FINE_FOR_KIDS = re.compile(rf"\b(suitable|appropriate|fine|ok|okay|safe|good|great|perfect|ideal|suited)\b[\w\s'-]{{0,25}}\b{YOUNG}\b"
                           rf"|\b(kid|family|child)-friendly\b|\bnot\b[\w\s'-]{{0,40}}\binappropriate\b[\w\s'-]{{0,15}}\b{YOUNG}\b")
# A hedge in the same clause ("unclear if it is suitable", "may not be suitable") keeps the answer.
HEDGE = re.compile(r"\b(not|no|never|unclear|unsure|whether|if|might|may|check|depends|doesn'?t know|don'?t know)\b|n['’]t\b")
CLAUSES = re.compile(r"[.;,!?]|\b(and|but|so|though|although|while)\b")
MATURE = ('horror', 'thriller', 'crime', 'war')  # genres that suggest older viewers
# "Does it fit tonight?": the answer must agree with the code's own yes/no for the time and the mood.
ABOUT_FIT = re.compile(r"\b(fit|fits|tonight|evening|enough time|time i have|time we have|right now)\b")
FITS_NO = re.compile(r"\b(doesn'?t|does not|won'?t|will not|not|may not|might not|isn'?t|is not)\b[\w\s'-]{0,20}"
                     r"\b(fit|match|suit|work)|too long|longer than|more than (the|your)|exceeds|runs over|over your|"
                     r"rather than|not enough time|not quite|instead of", re.I)
FITS_YES = re.compile(r"^\W*(yes|absolutely|sure)\b|\bfits?\b|\bwithin\b|enough time|\bperfect|\bmatch(es)?\b|\bsuits?\b", re.I)
ABOUT_DIRECTOR = re.compile(r"\bdirect|\bdirector|\bwho made\b|\bfilmmaker")
SENTENCE_END = re.compile(r'(?<=[a-z0-9)"”\'][.!?])\s+')
MAX_SENTENCES = 3
ABOUT_KIDS = re.compile(r"\b(kids?|children|child|family|famil(y|ies)|age|ages|young|scary|suitable|appropriate|rated|rating)\b")


def facts(item, pick=None, session=None):
    """What the model may say about `item` (a catalogue dict, as the API returns it) and why it was picked."""
    given = {k: item[k] for k in ('title', 'year', 'genres', 'tags', 'moods') if item.get(k)}
    given['kind'] = 'TV series' if item.get('series') else 'film'
    # The interface's words for intensity (SceneBar's energyWord), so "is it scary?" has something to go on.
    given['intensity'] = 'gentle' if item['intensity'] < 0.35 else 'intense' if item['intensity'] > 0.65 else 'balanced'
    series = item.get('series')
    given['minutes per episode' if series else 'minutes'] = item['minutes']
    if series:
        given.update(seasons=series['seasons'], episodes=series['episodes'], network=series.get('network'),
                     **({'ended': series['ended']} if series.get('ended') else {'still running': True}))
    given['description'] = item['description']
    if names := directors(item['description']):
        given['directed by'] = names  # said outright: small models miss it inside a long description
    # Said outright, because small models otherwise invent one ("rated PG-13") when asked about children.
    given['age rating'] = 'not known to Flicks'
    if pick:
        factors = pick['factors']
        strongest = sorted(factors, key=lambda k: -factors[k])[:2]
        given['why Flicks picked it'] = {
            'because you liked': pick.get('because', [])[:2],
            'themes shared with what you liked': pick.get('evidence', [])[:4],
            'main reasons': [('it is widely liked, while Flicks is still learning your taste'
                              if k == 'taste' and pick.get('popular') else FACTOR_WORDS[k])
                             for k in strongest if k in FACTOR_WORDS],
        }
    if session is not None:
        # Worked out here rather than left to the model: small models get arithmetic wrong, and say a horror
        # film "fits your relaxing evening". The mood test is the recommender's own (core.Recommender).
        fits = item['minutes'] <= session.minutes
        given['your evening'] = {'mood': session.mood, 'minutes available': session.minutes,
                                 ('one episode fits' if series else 'fits the time you have'): fits,
                                 'matches the mood you asked for': session.mood == 'any' or session.mood in item.get('moods', [])}
    return given


class TitleChat:
    def __init__(self, chat, catalog):
        self.chat = chat
        self.checker = Narrator(chat, catalog)  # reuses its title spotting (named_titles)

    def messages(self, given, question, history=()):
        question = ' '.join(str(question).split())[:MAX_QUESTION]
        if not question:
            raise ValueError('Ask a question about this title')
        turns = []
        for turn in list(history)[-MAX_TURNS:]:
            turns += [{'role': 'user', 'content': str(turn['question'])[:MAX_QUESTION]},
                      {'role': 'assistant', 'content': str(turn['answer'])[:600]}]
        system = SYSTEM + (' /no_think' if 'qwen3' in self.chat.model.lower() else '')
        return [{'role': 'system', 'content': system + '\n\nFacts:\n' + json.dumps(given, indent=1)},
                *turns, {'role': 'user', 'content': question}]

    def stream(self, given, question, history=()):
        """Yield {"delta"} events, then one {"done", "ok", "answer"|"note"}. Raises LLMError before any text."""
        stream = getattr(self.chat, 'stream', None)
        messages = self.messages(given, question, history)
        if stream is None:  # a loopback server client: one piece
            pieces = iter([self.chat.complete(messages, max_tokens=MAX_TOKENS)])
        else:
            pieces = stream(messages, max_tokens=MAX_TOKENS)
        text = ''
        for piece in pieces:
            text += piece
            yield {'delta': piece}
        try:
            yield {'done': True, 'ok': True, 'answer': self.check(text, given, question)}
        except LLMError as error:
            yield {'done': True, 'ok': False, 'note': str(error)}

    def check(self, reply, given, question=''):
        text = ' '.join(reply.split())
        if not text:
            raise LLMError('The model gave no answer')
        if re.search(r'https?://|www\.', text):
            raise LLMError('This answer was hidden because it included a link.')
        why = given.get('why Flicks picked it', {})
        allowed = {normalize(t) for t in [given['title'], *why.get('because you liked', [])]}
        allowed |= self.checker.named_titles(question)  # "Is it better than Alien?" may name Alien back
        description = f" {normalize(given['description'])} "
        quoted = {normalize(span) for span in re.findall('["“]([^"”]{2,80})["”]', text)}
        for title in self.checker.named_titles(text):
            # One-word titles are also names ("Marty" McFly, "Moon" in a sentence): only quoted ones count.
            if ' ' not in title and title not in quoted:
                continue
            # A title the description itself names (a sequel, the novel it adapts) is grounded too.
            if title not in allowed and f' {title} ' not in description:
                raise LLMError(f'This answer was hidden because it mentioned {self.checker.titles[title]}, '
                               'which Flicks didn’t give the model. Try asking another way.')
        asked = str(question).lower()
        # Flicks' own sentence replaces an answer that contradicts what Flicks knows for certain.
        if given.get('age rating') == UNKNOWN_RATING and ABOUT_KIDS.search(asked) and claims_fine_for_kids(text):
            return kids_sentence(given)
        named = given.get('directed by')
        if named and ABOUT_DIRECTOR.search(asked) and not any(n.split()[-1].lower() in text.lower() for n in named):
            return f'It was directed by {" and ".join(named)}.'
        if 'your evening' in given and ABOUT_FIT.search(asked) and contradicts_evening(text, given):
            return evening_sentence(given)
        return ' '.join(SENTENCE_END.split(text)[:MAX_SENTENCES])


def directors(description):
    """The names after "directed by" in a description: ["Roger Allers", "Rob Minkoff"], or []."""
    found = re.search(r'\bdirected by ', description)
    if not found:
        return []
    names, current = [], []
    for token in re.findall(r"[\w.'’-]+|,", description[found.end():]):
        if token in (',', 'and'):
            if current:
                names.append(' '.join(current))
                current = []
            continue
        if not token[0].isupper() or len(current) == 4:
            break
        ends = token.endswith('.') and len(token) > 2  # "Brooks." ends the sentence; "L." is an initial
        current.append(token.rstrip('.') if ends else token)
        if ends:
            break
    if current:
        names.append(' '.join(current))
    return names[:3]


def _evening(given):
    evening = given['your evening']
    time_ok = next((v for k, v in evening.items() if 'fit' in k), True)
    return time_ok, evening.get('matches the mood you asked for', True)


def contradicts_evening(text, given):
    """True when the answer says the opposite of the code's yes/no for tonight."""
    time_ok, mood_ok = _evening(given)
    text = text.replace('’', "'")
    says_no = bool(FITS_NO.search(text))
    says_yes = bool(FITS_YES.search(text)) and not says_no
    return says_no if time_ok and mood_ok else says_yes


def evening_sentence(given):
    """Flicks' own answer to "does it fit tonight?", from the time and mood it worked out."""
    evening = given['your evening']
    time_ok, mood_ok = _evening(given)
    series = 'minutes per episode' in given
    minutes = given.get('minutes per episode') if series else given.get('minutes')
    text = (f"{'Each episode runs' if series else 'It runs'} {minutes} minutes, "
            f"{'within' if time_ok else 'more than'} the {evening['minutes available']} you have")
    mood = evening.get('mood', 'any')
    if mood != 'any':
        moods = ' and '.join(given.get('moods', [])) or 'a different mood'
        text += f', and it is {mood}, as you asked' if mood_ok else f', and it is {moods} rather than {mood}'
    return text + ('. It fits tonight.' if time_ok and mood_ok else '. It may not suit tonight.')


def claims_fine_for_kids(text):
    """True when some clause says the title is fine for children without hedging."""
    sentences = re.split(r'(?<=[.!?])\s+', text.lower().replace('’', "'"))
    statements = ' '.join(s for s in sentences if not s.endswith('?'))  # an echoed "Is it OK for kids?" claims nothing
    # The double negative ("not … inappropriate") is itself the claim; elsewhere a "not" is a hedge.
    return any(clause and FINE_FOR_KIDS.search(clause) and ('inappropriate' in clause or not HEDGE.search(clause))
               for clause in CLAUSES.split(statements))


def kids_sentence(given):
    """Flicks' own answer to "is it OK for kids?", from facts it has, for when the model claimed more."""
    what = 'series' if given.get('kind') == 'TV series' else 'film'
    mature = [g for g in given.get('genres', []) if g in MATURE]
    text = 'Flicks doesn’t know its age rating, so check one before watching with children. '
    if given.get('intensity') == 'intense' or mature:
        how = f"an intense {what}" if given.get('intensity') == 'intense' else f"a {given.get('intensity', 'balanced')} {what}"
        genres = f" with {', '.join(mature)} in its genres" if mature else ''
        return text + f"It is {how}{genres}, which may be too much for young viewers."
    family = ' and listed as a family ' + what if 'family' in given.get('genres', []) else ''
    return text + f"It is {given.get('intensity', 'balanced')} in intensity{family}."
