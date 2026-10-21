"""Build the Ask student: labelled example requests, a tiny classifier trained on them, and its evaluation.

    python -m flicks.datasets.ask --out flicks/data/ask_student.json

The student reads the scene a person describes in their own words ("long week, I want to switch off,
nothing scary") into the same settings as the scene bar: mood, intensity, novelty, watch or listen, and
a genre to avoid. It replaces a local language model at runtime: it is ~1 MB of weights, answers in well
under a millisecond, and needs no model server (docs/adr/0014-ask-student.md).

Training requests are generated from a phrase bank: each phrase carries its labels, and a request joins
one to three phrases from different settings with everyday filler. The bank was written by the team
with an assistant's help (a language model as the teacher, offline, on public phrasing only). The
held-out set below is hand-written and shares no phrase with the bank, so it measures generalisation,
not memorisation. Requires NumPy (the `datasets` extra); the app itself does not.
"""
import argparse
import json
from pathlib import Path
import random
import time

from ..assistant.ask_student import FEATURES, HEADS, Student, featurize

# label: (head, value). Values must be in HEADS[head].
BANK = {
    ('mood', 'relaxing'): ['switch off', 'unwind', 'decompress', 'chill out', 'something calm', 'keep it mellow',
                           'wind down', 'relax after work', 'something cozy', 'a low key night', 'easy watching',
                           'nothing stressful', 'take my mind off things', 'something soothing', 'lazy sunday vibes',
                           'just veg out', 'something peaceful', 'a quiet night in', 'something comforting', 'zone out',
                           'curl up on the couch', 'put my feet up', 'something relaxing', 'unplug for a bit',
                           'lounge around', 'nothing taxing', 'tired brain', 'switch my brain off', 'cosy night',
                           'snuggle up', 'something tranquil', 'drift off', 'rest and recharge', 'flop on the sofa', 'sink into the couch', 'forget about work', 'something mellow', 'chill vibes', 'rainy day watch', 'sunday afternoon', 'after a long shift', 'i am exhausted', 'i am wiped out', 'destress', 'something low stakes', 'background comfort', 'easy on the brain', 'let my mind rest', 'doze off', 'fall asleep to', 'calm my nerves', 'nothing demanding', 'something breezy', 'slow evening', 'gentle evening', 'no stress please', 'a soothing one', 'cosy blanket night', 'wind down before bed', 'relaxed mood', 'unwind after work', 'take it easy', 'breathe out', 'i am tired'],
    ('mood', 'uplifting'): ['cheer me up', 'make me laugh', 'something happy', 'something feel good',
                            'put a smile on my face', 'lift my spirits', 'something fun', 'i had a rough day',
                            'something joyful', 'a good laugh', 'brighten my day', 'something wholesome',
                            'something hopeful', 'need a pick me up', 'something light hearted', 'a happy ending',
                            'make me smile', 'something funny', 'something silly', 'make me giggle', 'i feel sad',
                            'feeling blue', 'something sweet', 'something cheerful', 'bad day at work', 'a comedy',
                            'something charming', 'something upbeat', 'lighten the mood', 'something bright', 'crack me up', 'make me grin', 'today was awful', 'feeling low', 'need cheering up', 'warm and sunny', 'something warm', 'feel better', 'a laugh riot', 'funny bone', 'silly and fun', 'sunny vibes', 'wholesome fun', 'happy vibes', 'heartwarming', 'something joyous', 'lift me up', 'a bit of joy', 'good vibes only', 'laugh out loud', 'ridiculous comedy', 'i want to laugh', 'feeling down', 'pick me up', 'cheerful mood', 'something optimistic', 'i need a hug', 'smile a lot', 'light and happy', 'goofy'],
    ('mood', 'curious'): ['make me think', 'something clever', 'mind bending', 'blow my mind', 'learn something',
                          'a puzzle', 'something intriguing', 'make me wonder', 'keep me guessing', 'something smart',
                          'teach me something', 'a brain teaser', 'something fascinating', 'get my brain going',
                          'a mystery to solve', 'something with a twist', 'something educational but fun',
                          'something thought provoking', 'curious about history', 'challenge my mind',
                          'something cerebral', 'a head scratcher', 'i want to understand something new', 'brainy', 'something smart please', 'twisty', 'i will not figure out', 'a whodunit', 'mysterious', 'something to solve', 'ideas', 'big ideas', 'philosophical puzzle', 'science stuff', 'learn about', 'history', 'how things work', 'eye opening', 'something informative', 'unravel', 'clues', 'something intellectual', 'food for thought', 'expand my mind', 'true story', 'fascinating facts', 'curious mood', 'make my brain work', 'a riddle'],
    ('mood', 'tense'): ['on the edge of my seat', 'heart pounding', 'an adrenaline rush', 'something gripping',
                        'keep me on edge', 'white knuckle', 'thrill me', 'something suspenseful', 'pulse racing',
                        'nail biting', 'something nerve wracking', 'jolt me awake', 'keep me hooked',
                        'get my heart racing', 'something thrilling', 'an exciting one', 'wake me up',
                        'keep me alert', 'something tense', 'a thrill ride', 'excitement', 'something electric', 'blood pumping', 'jolt of excitement', 'on my toes', 'heart racing', 'edge of the seat', 'suspense', 'tension', 'thrilling ride', 'racing pulse', 'gripping thriller', 'can not look away', 'high stakes', 'keep me awake', 'adrenaline', 'dangerous', 'cat and mouse', 'ticking clock', 'nerves', 'breathless', 'pulse pounding', 'spine tingling', 'fight for survival', 'intense chase'],
    ('mood', 'reflective'): ['something deep', 'a good cry', 'something moving', 'something bittersweet',
                             'something meaningful', 'make me reflect', 'a melancholy mood', 'something poignant',
                             'quiet and thoughtful', 'something that stays with me', 'tug at my heartstrings',
                             'something profound', 'make me cry', 'something sad', 'an emotional one',
                             'something heartbreaking', 'tearjerker', 'something touching', 'gut wrenching drama',
                             'leave me thinking about life', 'a good weep', 'wreck me emotionally', 'cry my eyes out', 'tissues ready', 'emotional', 'heartbreak', 'grief', 'sad but beautiful', 'contemplative', 'melancholic', 'introspective', 'life lessons', 'lump in my throat', 'sombre', 'soul searching', 'quiet sadness', 'tear jerker', 'haunting and beautiful', 'something human', 'about loss', 'wistful', 'thoughtful drama'],
    ('intensity', 'low'): ['gentle', 'nothing too intense', 'slow paced', 'easygoing', 'something soft',
                           'nothing heavy', 'low energy', 'keep it light on action', 'nothing too wild', 'slow',
                           'calm pace', 'quiet', 'mild', 'low key', 'soft and slow', 'nothing loud', 'gently paced', 'not too much going on', 'calm', 'peaceful pace', 'subtle', 'understated', 'tame', 'low volume', 'nothing hectic'],
    ('intensity', 'high'): ['intense', 'action packed', 'high energy', 'explosive', 'fast paced', 'go big',
                            'nonstop action', 'full throttle', 'loud and big', 'chaotic', 'explosions', 'wild ride',
                            'crank it up', 'big action', 'pure chaos', 'explosions everywhere', 'all guns blazing', 'turbo', 'bombastic', 'over the top action', 'relentless', 'maximum energy', 'big stunts', 'high octane', 'adrenaline packed', 'a lot of action'],
    ('novelty', 'familiar'): ['something familiar', 'a comfort watch', 'nothing too weird', 'the usual',
                              'something safe', 'an old favourite kind of thing', 'nothing experimental',
                              'a classic i probably know', 'something predictable', 'comfort viewing', 'a favourite', 'an old cosy favourite', 'something i know', 'a rewatch', 'nostalgic', 'the classics', 'tried and true', 'familiar territory', 'something like i usually watch', 'my usual stuff', 'safe choice', 'reliable pick'],
    ('novelty', 'new'): ['something different', 'something i would never normally pick', 'out of my comfort zone',
                         'surprise me', 'something new', 'off the beaten path', 'something unexpected',
                         'a hidden gem', 'something weird', 'broaden my horizons', 'something unusual',
                         'something i have never heard of', 'try something new', 'surprising', 'random pick',
                         'something obscure', 'mix it up', 'something unexpected for once', 'throw me a curveball', 'scroll right past', 'stuff i would never pick', 'new to me', 'fresh', 'different from my usual', 'something left field', 'experimental', 'wild card', 'shake things up', 'an oddball pick', 'something unfamiliar', 'go off the map', 'something outside my taste'],
    ('medium', 'listen'): ['to listen to', 'while i cook', 'while driving', 'on my commute',
                           'in the background while i work', 'a podcast', 'for my walk', 'while i do the dishes',
                           'something to hear', 'for the gym', 'audio only', 'while i clean', 'for a run',
                           'on the train', 'while i drive', 'an episode', 'headphones on', 'while i work out',
                           'during chores', 'in the car', 'background noise', 'while i fold laundry', 'for my ears', 'drive home', 'on my run', 'in my earbuds', 'something to listen', 'listen while', 'podcast episode', 'while walking the dog', 'while i paint', 'commute home', 'in the background'],
    ('medium', 'watch'): ['to watch', 'a movie', 'a film', 'on the tv', 'on the big screen', 'something to see',
                          'movie night', 'a flick', 'a feature film', 'watch tonight', 'tv time', 'screen time', 'a picture', 'cinema', 'a movie to watch', 'a film to watch'],
    ('avoid', 'horror'): ['nothing scary', 'no horror', 'nothing creepy', 'no gore', 'not too scary',
                          'no jump scares', 'nothing frightening', 'no blood', 'nothing gory', 'i scare easily',
                          'no monsters', 'nothing violent and scary', 'keep the gore away', 'nothing that gives me nightmares', 'no nightmares', 'keep the blood out', 'squeamish', 'nothing spooky', 'no slashers', 'no ghosts', 'i hate horror', 'not horror', 'nothing disturbing', 'no zombies', 'no creepy stuff', 'easily scared'],
    ('avoid', 'romance'): ['no romance', 'nothing lovey dovey', 'no soppy love stories', 'skip the romance',
                           'no kissing movies', 'no love stories', 'nothing romantic', 'no rom coms', 'no lovey stuff', 'no romantic stuff', 'skip the love story', 'nothing mushy', 'no sappy stuff', 'no rom com', 'not romantic', 'hate romance'],
    ('avoid', 'musical'): ['no singing', 'no musicals', 'nothing with songs', 'no songs', 'no broadway', 'skip musicals', 'not a musical'],
    ('avoid', 'animation'): ['no cartoons', 'nothing animated', 'no kids cartoons', 'no animation',
                             'real actors only', 'skip the cartoons', 'no anime', 'not animated', 'no animated stuff', 'live action only', 'no pixar'],
    ('avoid', 'war'): ['no war movies', 'nothing about war', 'no battles', 'no soldiers', 'nothing military', 'no war stuff', 'skip war films'],
    ('avoid', 'documentary'): ['no documentaries', 'nothing educational', 'no docs', 'no true stories', 'nothing real life', 'skip documentaries', 'fiction only'],
}
GENERIC = ['recommend something', 'what should i watch', 'anything good', 'pick something for me', 'whatever',
           'something good', 'help me choose', 'i cant decide']
OFF_TOPIC = ['what is the weather', 'whats the time', 'what day is it', 'check my email', 'call my brother', 'how far is the moon', 'weather in london', 'convert dollars to euros', 'what is the news today', 'stock prices', 'play some music on spotify', 'set a timer', 'how do i fix my wifi', 'whats for dinner', 'directions to the station', 'how do i bake bread', 'set an alarm for seven', 'who won the game last night',
             'turn up the volume', 'order a pizza', 'what is two plus two', 'translate hello to french',
             'how tall is everest', 'send a message to mom', 'when is my next meeting', 'book a flight to paris',
             'whats the capital of spain', 'remind me to buy milk', 'how many cups in a litre']
PREFIXES = ['', '', 'honestly ', 'tonight ', 'ok ', 'hey ', 'i want ', 'i need ', 'find me ', 'can you find ',
            'give me ', 'looking for ', 'im in the mood for ', 'show me ', 'i just want to ', 'something to ']
JOINERS = [', ', ' and ', ' but ', ' - ', ' with ', '. ', ' ', ' also ']
SUFFIXES = ['', '', '', ' please', ' tonight', ' for tonight', ' right now', ' thanks']

# Hand-written, none of it in the bank: [text, {head: value}] (missing heads must be "none").
# Development set: hand-written before the bank was finished and used to grow it (its misses became bank
# phrases), so it no longer measures generalisation. TEST does.
DEV = [
    ['been a draining week, i just want to flop on the couch, nothing that gives me nightmares',
     {'mood': 'relaxing', 'avoid': 'horror'}],
    ['get my blood pumping', {'mood': 'tense'}],
    ['crack me up, today was awful', {'mood': 'uplifting'}],
    ['background noise while i fold laundry', {'medium': 'listen'}],
    ['show me stuff i would normally scroll right past', {'novelty': 'new'}],
    ['let me sink into the sofa and forget about work', {'mood': 'relaxing'}],
    ['i need a jolt of excitement', {'mood': 'tense'}],
    ['how do i bake sourdough', {}],
    ['what time is it in tokyo', {}],
    ['i could use a good weep', {'mood': 'reflective'}],
    ['something mellow for a rainy evening', {'mood': 'relaxing'}],
    ['a twisty one i will not figure out', {'mood': 'curious'}],
    ['something that will make me grin, no lovey stuff', {'mood': 'uplifting', 'avoid': 'romance'}],
    ['something for my ears on the drive home', {'medium': 'listen'}],
    ['pure chaos, explosions everywhere', {'intensity': 'high'}],
    ['soft and slow, i want to doze off', {'mood': 'relaxing', 'intensity': 'low'}],
    ['throw me a curveball', {'novelty': 'new'}],
    ['an old cosy favourite kind of film', {'novelty': 'familiar', 'medium': 'watch'}],
    ['skip the cartoons, give me something brainy', {'mood': 'curious', 'avoid': 'animation'}],
    ['what is the stock price of apple', {}],
    ['i am squeamish so keep the blood out of it', {'avoid': 'horror'}],
    ['something that will wreck me emotionally', {'mood': 'reflective'}],
    ['something to keep me awake and on my toes', {'mood': 'tense'}],
    ['i want to learn about ancient rome on my run', {'mood': 'curious', 'medium': 'listen'}],
    ['feeling low, need something warm and sunny', {'mood': 'uplifting'}],
]


# Test set: hand-written after the bank, features and DEV were final; reported once (docs/adr/0014-ask-student.md).
TEST = [
    ['my brain is fried, nothing complicated tonight', {'mood': 'relaxing'}],
    ['laughing till my stomach hurts', {'mood': 'uplifting'}],
    ['something that makes me feel clever', {'mood': 'curious'}],
    ['scare-free please, my kid is watching with me', {'avoid': 'horror'}],
    ['one where i try to work out who did it', {'mood': 'curious'}],
    ['an evening of sobbing into my pillow', {'mood': 'reflective'}],
    ['heart in my throat the whole time', {'mood': 'tense'}],
    ['an audio thing for my jog', {'medium': 'listen'}],
    ['nothing too heavy, slow and gentle', {'intensity': 'low'}],
    ['big dumb action with car chases', {'intensity': 'high'}],
    ['pick something offbeat i have not seen', {'novelty': 'new'}],
    ['what is the population of canada', {}],
    ['play me a song', {}],
    ['a wholesome pick to cheer up my mom', {'mood': 'uplifting'}],
    ['skip anything with song and dance numbers', {'avoid': 'musical'}],
    ['get my pulse up, but not a cartoon', {'mood': 'tense', 'avoid': 'animation'}],
    ['a calming thing to drift to sleep with', {'mood': 'relaxing'}],
    ['a deep, quiet drama about growing old', {'mood': 'reflective'}],
    ['teach me about the ocean while i do chores', {'mood': 'curious', 'medium': 'listen'}],
    ['comfort rewatch energy', {'novelty': 'familiar'}],
    ['hit me with an oddity', {'novelty': 'new'}],
    ['no smooching scenes please', {'avoid': 'romance'}],
    ['give me goosebumps of excitement', {'mood': 'tense'}],
    ['i am bummed out, lift me', {'mood': 'uplifting'}],
    ['how long does it take to boil an egg', {}],
    ['lazy saturday, keep it easy', {'mood': 'relaxing'}],
    ['frantic and loud, all action', {'intensity': 'high'}],
    ['made up stories only, nothing nonfiction', {'avoid': 'documentary'}],
    ['a poignant story about friendship', {'mood': 'reflective'}],
    ['an audio show to keep me company on the bus', {'medium': 'listen'}],
]


def generate(n=6000, seed=4907):
    """Labelled requests from the bank: (text, {head: value}) with every head present."""
    rng = random.Random(seed)
    slots = list(BANK)
    rows = []
    for _ in range(n):
        roll = rng.random()
        labels = dict.fromkeys(HEADS, 'none')
        if roll < 0.08:
            text = rng.choice(OFF_TOPIC)
        elif roll < 0.13:
            text = rng.choice(GENERIC)
        else:
            chosen, heads = [], set()
            for slot in rng.sample(slots, len(slots)):
                if slot[0] not in heads:
                    chosen.append(slot)
                    heads.add(slot[0])
                if len(chosen) >= rng.choice((1, 1, 2, 2, 3)):
                    break
            parts = [rng.choice(BANK[slot]) for slot in chosen]
            text = parts[0]
            for part in parts[1:]:
                text += rng.choice(JOINERS) + part
            for head, value in chosen:
                labels[head] = value
        text = (rng.choice(PREFIXES) + text + rng.choice(SUFFIXES)).strip()
        rows.append((text, labels))
    return rows


def train(rows, epochs=60, batch=256, rate=0.05, l2=1e-5, seed=4907):
    """Softmax regression per head over hashed features, mini-batch Adam. Returns a Student."""
    import numpy as np
    rng = np.random.default_rng(seed)
    dim = FEATURES['dim']
    x = np.zeros((len(rows), dim), dtype=np.float32)
    for i, (text, _) in enumerate(rows):
        for index, value in featurize(text).items():
            x[i, index] += value
    weights, biases = {}, {}
    for head, classes in HEADS.items():
        y = np.eye(len(classes), dtype=np.float32)[[classes.index(labels[head]) for _, labels in rows]]
        params = [np.zeros((dim, len(classes)), dtype=np.float32), np.zeros(len(classes), dtype=np.float32)]
        moments = [[np.zeros_like(p), np.zeros_like(p)] for p in params]
        step = 0
        for _ in range(epochs):
            order = rng.permutation(len(rows))
            for start in range(0, len(rows), batch):
                idx = order[start:start + batch]
                logits = x[idx] @ params[0] + params[1]
                logits -= logits.max(axis=1, keepdims=True)
                p = np.exp(logits)
                p /= p.sum(axis=1, keepdims=True)
                error = (p - y[idx]) / len(idx)
                grads = [x[idx].T @ error + l2 * params[0], error.sum(axis=0)]
                step += 1
                for param, grad, (m, v) in zip(params, grads, moments, strict=True):
                    m[:] = 0.9 * m + 0.1 * grad
                    v[:] = 0.999 * v + 0.001 * grad * grad
                    param -= rate * (m / (1 - 0.9 ** step)) / (np.sqrt(v / (1 - 0.999 ** step)) + 1e-8)
        weights[head], biases[head] = params
    return Student.from_arrays(weights, biases)


def evaluate(student, cases=None):
    """Per-head accuracy and whole-request exact match, with the gated predictions (default: the test set)."""
    cases = TEST if cases is None else cases
    per_head = dict.fromkeys(HEADS, 0)
    exact, rows = 0, []
    start = time.perf_counter()
    for text, expected in cases:
        got = student.settings(text)
        want = {head: expected.get(head, 'none') for head in HEADS}
        for head in HEADS:
            per_head[head] += got.get(head, 'none') == want[head]
        ok = all(got.get(head, 'none') == want[head] for head in HEADS)
        exact += ok
        rows.append({'text': text, 'pass': ok, 'got': got})
    micros = (time.perf_counter() - start) / len(cases) * 1e6
    return {'cases': len(cases), 'exact': exact, 'per_head': {h: round(v / len(cases), 3) for h, v in per_head.items()},
            'microseconds_per_request': round(micros, 1), 'rows': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Train the Ask student and evaluate it on held-out requests')
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1]/'data'/'ask_student.json')
    parser.add_argument('--examples', type=int, default=6000)
    parser.add_argument('--evaluate-only', action='store_true', help='Score the weights at --out without retraining')
    args = parser.parse_args(argv)
    if not args.evaluate_only:
        student = train(generate(args.examples))
        student.save(args.out)
    student = Student.load(args.out)
    report = {name: evaluate(student, cases) for name, cases in (('test', TEST), ('dev', DEV))}
    for result in report.values():
        result['rows'] = [r for r in result['rows'] if not r['pass']]  # only the misses are worth reading
    print(json.dumps({**report, 'weights': str(args.out), 'bytes': args.out.stat().st_size}, indent=1))


if __name__ == '__main__':
    main()
