"""Ask Flicks, third tier: a local language model that plans with tools when the rules and System One cannot.

Requests go to the cheapest reader that can answer: the deterministic rules (microseconds), then the
local System One model if one is configured (hundreds of milliseconds), and only then this agent
(seconds). The agent never acts. It may look titles up, then must finish with one proposal of the same
kinds the rules produce (a scene change, a search, titles like one it looked up, or a title to play).
Flicks validates the proposal like a manual setting and the user still previews and applies it. It
cannot rate, delete or download anything. docs/adr/0013-local-llm.md.
"""
from collections import OrderedDict
from dataclasses import asdict
import json
import threading
import time

from ..core import MEDIUMS, MOODS, Session
from ..text import normalize
from .commands import describe_patch
from .llm import LLMError, parse_json

MAX_STEPS = 4
CACHE_SECONDS = 15 * 60

TOOLS = """You help a person choose a film or podcast in Flicks. Answer with one JSON object per turn:
{"tool": "<name>", "args": {...}}
Tools:
- lookup_title {"title": str}: find catalogue titles by name; returns their ids.
- finish_similar {"id": str, "reply": str}: show titles like one you looked up. Use for "like X", "similar to X".
- finish_scene {"mood"?: str, "max_minutes"?: int, "intensity"?: number 0-1, "novelty"?: number 0-1,
  "avoid_genres"?: [str], "medium"?: "any"|"watch"|"listen", "reply": str}: describe the viewing scene.
  Use when the person describes a feeling, energy, length or things to avoid.
- finish_search {"query": str, "reply": str}: search with a few words (genre, topic, decade, person).
  Use when the person describes what the film is about.
- finish_play {"id": str, "reply": str}: play a title you looked up, only if they asked to play or watch it now.
- give_up {"reply": str}: the request is not about choosing something to watch or listen to.
Moods: {moods}. Genres: {genres}.
Intensity 0.2 is gentle, 0.9 is intense. Novelty 0.1 is familiar, 0.9 is new territory.
Only use ids returned by lookup_title. Finish within 4 turns. "reply" is one short sentence to the person.
Examples:
"something like Arrival but shorter" -> {"tool": "lookup_title", "args": {"title": "Arrival"}}, then
  {"tool": "finish_similar", "args": {"id": "<id from the result>", "reply": "Titles like Arrival."}}
"long week, I want to switch off, nothing scary" -> {"tool": "finish_scene", "args": {"mood": "relaxing",
  "intensity": 0.2, "avoid_genres": ["horror"], "reply": "Something calm and gentle."}}
"an adrenaline rush" -> {"tool": "finish_scene", "args": {"mood": "tense", "intensity": 0.9, "reply": "High energy."}}
"that film about a robot cleaning up earth" -> {"tool": "finish_search", "args": {"query": "robot earth",
  "reply": "Searching for robot films."}}
"what is the weather" -> {"tool": "give_up", "args": {"reply": "I can only help you pick something to watch."}}"""


class GaveUp(LLMError):
    """The model judged the request not to be about choosing something; its reply says why."""


class AgentInterpreter:
    """Wraps another interpreter (rules, or rules + System One) and consults the model only when it is stuck."""

    def __init__(self, inner, chat, catalog, titles, playable=None):
        self.inner, self.chat, self.titles = inner, chat, titles
        self.playable = playable or (lambda content_id: False)
        self.by_id = {item.id: item for item in catalog}
        self.genres = sorted({g for item in catalog for g in item.genres})
        self.name = f'{inner.name} + {chat.name}'
        self.system = TOOLS.replace('{moods}', ', '.join(MOODS[1:])).replace('{genres}', ', '.join(self.genres))
        # Preview and apply parse the same text: the cache makes apply get exactly what was previewed.
        self.cache, self.lock = OrderedDict(), threading.Lock()

    def parse(self, text):
        result = self.inner.parse(text)  # validates length and type, and raises ValueError itself
        if not self.stuck(result):
            return result
        key = normalize(text)
        with self.lock:
            hit = self.cache.get(key)
            if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
                return hit[1]
        reason = None
        try:
            proposal = self.run(text)
        except LLMError as error:
            proposal, reason = None, str(error)
        if proposal is None:
            note = f'The local model could not help ({reason}).'
            return {**result, 'note': ' '.join(filter(None, [result.get('note'), note]))}
        with self.lock:
            self.cache[key] = (time.monotonic(), proposal)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
        return proposal

    @staticmethod
    def stuck(result):
        """Rules win: the model is asked only when nothing specific was understood, or a named title was not found."""
        return result.get('fallback') or (result['intent'] == 'unknown' and result.get('reason') in ('unrecognized', 'not_found'))

    def run(self, text):
        messages = [{'role': 'system', 'content': self.system}, {'role': 'user', 'content': text}]
        seen, steps = {}, []
        for _ in range(MAX_STEPS):
            reply = self.chat.complete(messages, json_mode=True, max_tokens=200)
            messages.append({'role': 'assistant', 'content': reply})
            try:
                call = parse_json(reply)
                tool = call.get('tool')
                # Small models sometimes put the arguments beside "tool" instead of inside "args".
                args = call['args'] if 'args' in call else {k: v for k, v in call.items() if k != 'tool'}
                if not isinstance(args, dict):
                    raise ValueError('args must be an object')
                if tool == 'lookup_title':
                    found = self.lookup(args.get('title'))
                    seen.update((item.id, item) for item in found)
                    steps.append(f'Looked up “{args.get("title")}”: {len(found)} found')
                    observation = [{'id': i.id, 'title': i.title, 'year': i.year, 'minutes': i.minutes} for i in found] or 'no titles found'
                else:
                    proposal = self.finish(tool, args, seen)
                    return {**proposal, 'parser': 'llm', 'steps': steps,
                            'note': f'Planned by {self.chat.name}. Review it before applying.'}
            except GaveUp:
                raise
            except (LLMError, ValueError, TypeError) as error:
                observation = f'error: {error}'
            messages.append({'role': 'user', 'content': 'Tool result: ' + json.dumps(observation)})
        raise LLMError('it did not finish in time')

    def lookup(self, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
            raise ValueError('title must be 1 to 100 characters')
        exact = [i for i in self.by_id.values() if normalize(i.title) == normalize(title)]
        if exact:
            return exact[:5]
        page, _, _ = self.titles.search(title, None, 0, 5)
        return page

    def finish(self, tool, args, seen):
        reply = args.get('reply')
        reply = reply.strip()[:200] if isinstance(reply, str) and reply.strip() else None
        if tool == 'give_up':
            raise GaveUp(reply or 'it can only help choose something to watch or listen to')
        if tool == 'finish_scene':
            patch = self.scene(args)
            return {'intent': 'session', 'patch': patch, 'summary': describe_patch(patch), 'reply': reply}
        if tool in ('finish_similar', 'finish_play'):
            item = seen.get(args.get('id'))
            if item is None:
                raise ValueError('use an id returned by lookup_title')
            if tool == 'finish_similar':
                return {'intent': 'search', 'similar': item.id, 'summary': f'Show titles like {item.title}',
                        'content': asdict(item), 'reply': reply}
            return {'intent': 'play', 'id': item.id, 'summary': f'Play {item.title}', 'content': asdict(item), 'reply': reply}
        if tool == 'finish_search':
            query = args.get('query')
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100:
                raise ValueError('query must be 1 to 100 characters')
            _, total, understood = self.titles.search(query, None, 0, 1)
            if not total:
                raise ValueError('that search matches nothing; try other words, or give_up if this is not about films')
            parts = understood.labels() + [f'“{w}”' for w in understood.words]
            return {'intent': 'search', 'query': normalize(query), 'summary': 'Search for ' + (' · '.join(parts) or query),
                    'reply': reply}
        raise ValueError(f'unknown tool {tool!r}')

    def scene(self, args):
        """A Session patch from the model's arguments, checked exactly like the manual controls."""
        patch = {}
        if 'mood' in args:
            if args['mood'] not in MOODS:
                raise ValueError(f'mood must be one of {", ".join(MOODS)}')
            patch['mood'] = args['mood']
        if 'max_minutes' in args:
            if type(args['max_minutes']) is not int:
                raise ValueError('max_minutes must be a whole number')
            patch['minutes'] = args['max_minutes']
        for field in ('intensity', 'novelty'):
            if field in args:
                patch[field] = args[field]
        if 'avoid_genres' in args:
            wanted = args['avoid_genres']
            if not isinstance(wanted, list):
                raise ValueError('avoid_genres must be a list')
            by_name = {g.casefold(): g for g in self.genres}
            unknown = [g for g in wanted if not isinstance(g, str) or g.casefold() not in by_name]
            if unknown:
                raise ValueError(f'unknown genres {unknown}; use the genre list')
            patch['excluded_genres'] = [by_name[g.casefold()] for g in wanted]
        if 'medium' in args:
            if args['medium'] not in MEDIUMS:
                raise ValueError('medium must be any, watch or listen')
            patch['medium'] = args['medium']
        if not patch:
            raise ValueError('finish_scene needs at least one setting')
        Session(**patch)  # the same validation as the manual controls; raises ValueError
        return patch
