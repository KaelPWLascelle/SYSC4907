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
        # Worked out here rather than left to the model: small models get arithmetic wrong.
        fits = item['minutes'] <= session.minutes
        given['your evening'] = {'mood': session.mood, 'minutes available': session.minutes,
                                 ('one episode fits' if series else 'fits the time you have'): fits}
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
        return text
