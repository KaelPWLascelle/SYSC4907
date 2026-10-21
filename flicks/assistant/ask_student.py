"""The Ask student: a tiny distilled classifier that reads a described scene into scene settings.

It runs in this process, in well under a millisecond, from a small JSON file of weights
(flicks/data/ask_student.json, built by `python -m flicks.datasets.ask`). It replaces a local language
model at runtime (docs/adr/0014-ask-student.md): no model server, no gigabytes of memory.

Like every reader in Ask Flicks it only proposes. The deterministic rules run first and win; the student
adds what they could not read; low-confidence answers are dropped; the result passes the same Session
validation as the manual controls and the user still previews and applies it.
"""
from dataclasses import asdict
from itertools import pairwise
import json
import math
from pathlib import Path
import re
import zlib

from ..core import Session
from ..text import normalize
from .commands import describe_patch

DEFAULT_WEIGHTS = Path(__file__).parents[1]/'data'/'ask_student.json'
FEATURES = {'name': 'hashed-words-v2', 'dim': 8192}
HEADS = {
    'mood': ['none', 'relaxing', 'uplifting', 'curious', 'tense', 'reflective'],
    'intensity': ['none', 'low', 'high'],
    'novelty': ['none', 'familiar', 'new'],
    'avoid': ['none', 'horror', 'romance', 'musical', 'animation', 'war', 'documentary'],
}
VALUES = {'intensity': {'low': 0.2, 'high': 0.9}, 'novelty': {'familiar': 0.1, 'new': 0.9}}
MIN_CONFIDENCE = 0.6
CUE = re.compile(r'\b(like|similar to|in the vein of|same as|reminds me of|play|put on|watch|start|resume)\s+')
PLAY_CUES = frozenset({'play', 'put on', 'watch', 'start', 'resume'})
# Words that say a request is about something to find, so a keyword search must not be dropped for a scene.
TOPIC = re.compile(r'\b(?:about|featuring|starring|set in|based on|with|find|search|show me|play|put on)\b')


def featurize(text):
    """Hashed word unigrams and bigrams, 5-letter prefixes and letter 4-grams, each weighted 1/sqrt(count).

    The letter fragments let unseen forms share signal with trained ones ("scare"/"scary", "laughing").
    """
    words = normalize(text).split()
    grams = [f'w:{w}' for w in words] + [f'b:{a} {b}' for a, b in pairwise(words)]
    grams += [f'p:{w[:5]}' for w in words if len(w) > 5]
    grams += [f'c:{padded[i:i + 4]}' for w in words if len(w) > 3 for padded in [f'<{w}>'] for i in range(len(padded) - 3)]
    if not grams:
        return {}
    weight = 1 / math.sqrt(len(grams))
    features = {}
    for gram in grams:
        index = zlib.crc32(gram.encode()) % FEATURES['dim']
        features[index] = features.get(index, 0) + weight
    return features


class Student:
    def __init__(self, weights, biases):
        # weights[head][class] = {feature index: weight}, sparse; biases[head][class] = float
        self.weights, self.biases = weights, biases

    @classmethod
    def from_arrays(cls, weights, biases, keep=0.005):
        sparse = {head: {cls_: {int(i): round(float(v), 4) for i, v in enumerate(weights[head][:, k]) if abs(v) > keep}
                         for k, cls_ in enumerate(HEADS[head])} for head in HEADS}
        return cls(sparse, {head: {c: round(float(b), 4) for c, b in zip(HEADS[head], biases[head], strict=True)}
                            for head in HEADS})

    def save(self, path):
        data = {'features': FEATURES, 'heads': HEADS, 'biases': self.biases,
                'weights': {h: {c: {str(i): v for i, v in w.items()} for c, w in cs.items()} for h, cs in self.weights.items()}}
        Path(path).write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')

    @classmethod
    def load(cls, path=DEFAULT_WEIGHTS):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('features') != FEATURES or data.get('heads') != HEADS:
            raise ValueError(f'{path} was built for different features or settings; rebuild it with python -m flicks.datasets.ask')
        weights = {h: {c: {int(i): float(v) for i, v in w.items()} for c, w in cs.items()} for h, cs in data['weights'].items()}
        for classes in weights.values():
            for values in classes.values():
                if any(not math.isfinite(v) for v in values.values()):
                    raise ValueError(f'{path} contains a non-finite weight')
        return cls(weights, data['biases'])

    def probabilities(self, text):
        x = featurize(text)
        result = {}
        for head, classes in HEADS.items():
            logits = [self.biases[head][c] + sum(v * self.weights[head][c].get(i, 0.0) for i, v in x.items()) for c in classes]
            top = max(logits)
            exps = [math.exp(z - top) for z in logits]
            total = sum(exps)
            result[head] = {c: e / total for c, e in zip(classes, exps, strict=True)}
        return result

    def settings(self, text, min_confidence=MIN_CONFIDENCE):
        """{head: value} for every head the student is confident about (never "none")."""
        chosen = {}
        for head, probs in self.probabilities(text).items():
            value = max(probs, key=probs.get)
            if value != 'none' and probs[value] >= min_confidence:
                chosen[head] = value
        return chosen


class StudentInterpreter:
    """Wraps the rules (or rules + System One) and fills in what they could not read."""

    def __init__(self, inner, student, catalog, titles, playable=None):
        self.inner, self.student, self.titles = inner, student, titles
        self.playable = playable or (lambda content_id: False)
        self.genres = {g for item in catalog for g in item.genres}
        self.by_title = {}
        for item in catalog:
            self.by_title.setdefault(normalize(item.title), []).append(item)
        self.name = f'{inner.name} + Ask student'

    def parse(self, text):
        result = self.inner.parse(text)  # validates length and type itself
        if result['intent'] in ('feedback', 'play') or result.get('similar') or result.get('reason') == 'refused':
            return result  # the rules read something specific, or deliberately declined: they win
        named = self.named_title(text)
        if named is not None:
            return named  # a title after a cue word, even with words the rules could not strip ("… but lighter")
        if result.get('reason') == 'not_found':
            return result  # a named title nobody could find: never replaced by a mood; the agent may retry it
        patch = self.patch(text)
        if not patch:
            return result
        Session(**patch)
        if result['intent'] == 'session':
            extra = {k: v for k, v in patch.items() if k not in result['patch']}
            if not extra:
                return result
            merged = {**result['patch'], **extra}
            Session(**merged)
            return {**result, 'patch': merged, 'summary': describe_patch(merged), 'parser': 'rules+student',
                    'note': 'The Ask student read the rest of your words. Review before applying.'}
        if result['intent'] == 'search':
            understood = self.titles.understand(text)
            if understood.genres or understood.years:
                return result  # a search that understood what to find ("funny films from the 90s") stands
        if result['intent'] == 'search' and TOPIC.search(normalize(text)):
            # "something sad about dogs": keep the search for what it is about, and set the scene too.
            scene = describe_patch(patch)
            return {**result, 'patch': patch, 'parser': 'rules+student',
                    'summary': f"{result['summary']}, and {scene[0].lower()}{scene[1:]}",
                    'note': 'The search keeps your words; the Ask student set the scene from them.'}
        return {'intent': 'session', 'patch': patch, 'summary': describe_patch(patch), 'parser': 'student',
                'note': 'Read by the Ask student on this device. Review before applying.'}

    def patch(self, text):
        settings = self.student.settings(text)
        patch = {}
        if 'mood' in settings:
            patch['mood'] = settings['mood']
        for head in ('intensity', 'novelty'):
            if head in settings:
                patch[head] = VALUES[head][settings[head]]
        if settings.get('avoid') in self.genres:
            patch['excluded_genres'] = [settings['avoid']]
        return patch

    def named_title(self, text):
        """"watch something like The Martian but lighter": the longest catalogue title right after any cue word."""
        clean = normalize(text)
        for cue in CUE.finditer(clean):
            words = clean[cue.end():].split()
            for end in range(min(len(words), 12), 0, -1):
                items = self.by_title.get(' '.join(words[:end]))
                if items and len(items) == 1 and (end > 1 or len(words[0]) >= 4):
                    item = items[0]
                    if cue[1] in PLAY_CUES:
                        # Like the rules' "play X": the interface plays it, or says it cannot be played here.
                        return {'intent': 'play', 'id': item.id, 'summary': f'Play {item.title}', 'content': asdict(item),
                                'parser': 'student'}
                    return {'intent': 'search', 'similar': item.id, 'summary': f'Show titles like {item.title}',
                            'content': asdict(item), 'parser': 'student'}
        return None
