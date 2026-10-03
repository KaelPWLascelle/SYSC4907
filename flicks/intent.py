"""System One fallback for free-text requests the deterministic rules do not understand.

Rules run first and win whenever they recognise something. Only when they return ``unknown`` does a
local System One model get asked typed questions about the text. The model can only choose among
options this file defines; its answers pass the same ``Session`` validation as manual controls, and
low-confidence answers are dropped rather than guessed. The request text never leaves the machine:
``DecisionClient.decide(private=True)`` refuses non-loopback backends.
"""
from .commands import CommandInterpreter, normalize
from .core import MOODS, Session
from .systemone import DecisionClient, PrivacyError, SystemOneError, choice, noul

MOOD_WORDS = {
    'relaxing': 'calm, cozy, soothing, gentle, chill, comforting, unwind, quiet, easy',
    'uplifting': 'happy, cheerful, funny, warm, feel good, heartwarming, hopeful, fun, joyful',
    'curious': 'interesting, mind bending, clever, mystery, learn, discover, ideas, puzzle, weird',
    'tense': 'thrilling, suspense, edge of my seat, scary, gripping, adrenaline, dark, creepy',
    'reflective': 'thoughtful, deep, moving, sad, melancholy, meaningful, contemplative, slow',
}


class SystemOneInterpreter:
    name = 'Local command rules + System One'

    def __init__(self, catalog, client: DecisionClient, min_confidence=0.6, min_exclusion=0.8):
        if not client.backend.local:
            raise PrivacyError('The command assistant needs a System One model on this machine (127.0.0.1)')
        self.rules, self.client = CommandInterpreter(catalog), client
        self.min_confidence, self.min_exclusion = min_confidence, min_exclusion
        self.genres = self.rules.genres
        self.questions = {
            'mood': choice('Which viewing mood is the person asking for?',
                           {**MOOD_WORDS, 'unspecified': 'no particular mood, not stated'}),
            **{f'avoid_{i}': noul(f'Does the person ask to avoid {genre} films?',
                                  no=f'wants, include, likes, {genre}',
                                  yes=f'no, not, avoid, without, skip, hate, nothing, {genre}')
               for i, genre in enumerate(self.genres)},
        }

    def parse(self, text):
        result = self.rules.parse(text)  # validates length/type and raises ValueError itself
        if result['intent'] != 'unknown' or result.get('reason') != 'unrecognized':
            return result  # never let a model override a deliberate refusal (e.g. negation)
        clean = normalize(text)
        mentioned = [i for i, g in enumerate(self.genres) if normalize(g) in clean]
        questions = {'mood': self.questions['mood'], **{f'avoid_{i}': self.questions[f'avoid_{i}'] for i in mentioned}}
        try:
            answers = self.client.decide(text, questions, private=True)
        except SystemOneError:
            return {**result, 'note': 'The local System One model was unavailable; only exact commands work.'}
        patch, reasons = {}, []
        mood = answers['mood']
        if mood.value in MOODS[1:] and mood.answer_confidence >= self.min_confidence:
            patch['mood'] = mood.value
            reasons.append(f'mood {mood.value} ({mood.answer_confidence:.0%})')
        excluded = [self.genres[i] for i in mentioned if answers[f'avoid_{i}'].expected >= self.min_exclusion]
        if excluded:
            patch['excluded_genres'] = excluded
            reasons.append('avoid ' + ', '.join(excluded))
        if not patch:
            return {**result, 'parser': 'rules+systemone',
                    'note': f'The local model was not confident enough to change anything (mood: {mood.value}, {mood.answer_confidence:.0%}).'}
        Session(**patch)  # same validation as manual controls
        return {'intent': 'session', 'patch': patch, 'parser': 'systemone',
                'summary': 'Set ' + '; '.join(reasons) + '.',
                'note': f'Interpreted by {self.client.backend.name}. Percentages are model confidence; preview before applying.'}
