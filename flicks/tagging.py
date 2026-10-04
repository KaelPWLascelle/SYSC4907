"""Build-time catalogue tagging with a System One teacher, plus a decision layer that uses the tags.

Only public catalogue fields (title, year, genres, description) are sent. Editorial moods and
intensity are withheld from the model so they can serve as a small gold set.

    python -m flicks.tagging --out work/tags.json                      # offline lexical stand-in
    python -m flicks.tagging --url http://127.0.0.1:8000 --out work/tags.json   # laya-serve / Kev
    python -m flicks.tagging --url https://api.typesafe.ai --api-key-env TYPESAFE_API_KEY --out ...
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean
from .core import MOODS, HeuristicDecision, load_catalog
from .systemone import (Answer, DecisionClient, HttpBackend, LexicalBackend, SystemOneError, choice,
                        expected_calibration_error, noul, options, score, validate_questions)

SCHEMA_VERSION = 1

FILM_QUESTIONS = validate_questions({
    'mood': choice('Which viewing mood does this film best suit?', {
        'relaxing': 'calm, gentle, cozy, soothing, comforting, easygoing, quiet, low stakes',
        'uplifting': 'hopeful, warm, joyful, funny, heartwarming, triumphant, feel good, friendship, comedy',
        'curious': 'intriguing ideas, mystery, discovery, science, puzzle, exploration, wonder, documentary',
        'tense': 'suspense, danger, fear, horror, threat, chase, survival, dread, crime, thriller',
        'reflective': 'thoughtful, melancholy, memory, loss, loneliness, meaning, philosophical, drama',
    }),
    'intensity': score('How intense is this film to watch?', [
        'gentle, nothing upsetting',
        'mild peril or conflict',
        'moderate tension, action or conflict',
        'intense danger, violence, horror or fear',
        'extreme, harrowing or graphic',
    ]),
    'pace': score('How fast-paced is this film?', [
        'slow, quiet, contemplative',
        'steady, conversational',
        'brisk, fast-moving, action, chase',
    ]),
    'family': noul('Is this film suitable to watch with young children?',
                   no='violence, horror, fear, killer, crime, mature, disturbing, dread',
                   yes='family, animation, children, gentle, friendly, adventure, comedy, musical'),
})


def film_state(item):
    """The only fields a teacher sees. Never add editorial moods/intensity or user data here."""
    return {'title': item.title, 'year': item.year, 'genres': item.genres, 'description': item.description}


def questions_hash(questions):
    return hashlib.sha256(json.dumps(questions, sort_keys=True).encode()).hexdigest()[:16]


def answer_to_json(answer: Answer):
    return {'value': answer.value, 'probabilities': {k: round(v, 6) for k, v in answer.probabilities.items()},
            'answer_confidence': round(answer.answer_confidence, 6),
            'normalized': round(answer.normalized, 6)}


def tag_catalog(catalog, client: DecisionClient, questions=FILM_QUESTIONS):
    tags, failures = {}, {}
    for item in catalog:
        try:
            answers = client.decide(film_state(item), questions, private=False)
            tags[item.id] = {qid: answer_to_json(a) for qid, a in answers.items()}
        except SystemOneError as exc:  # keep going; a partial tag file is still useful and honest
            failures[item.id] = str(exc)
    return {'schema_version': SCHEMA_VERSION, 'backend': client.backend.name,
            'created': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'questions_sha256': questions_hash(questions), 'questions': questions,
            'tags': tags, 'failures': failures}


def load_tags(path, catalog=None):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema_version') != SCHEMA_VERSION or not isinstance(data.get('tags'), dict):
        raise ValueError('Unsupported tag file')
    validate_questions(data['questions'])
    if catalog is not None and set(data['tags']) - {item.id for item in catalog}:
        raise ValueError('Tag file mentions content IDs that are not in this catalogue')
    def number(v):
        return type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1

    for row in data['tags'].values():
        if not isinstance(row, dict):
            raise ValueError('Tag file contains an invalid tag')
        for qid, tag in row.items():
            question = data['questions'].get(qid)
            p = tag.get('probabilities') if isinstance(tag, dict) else None
            if (question is None or not isinstance(p, dict) or set(p) != set(options(question))
                    or not all(number(v) for v in p.values()) or not 0.98 <= sum(p.values()) <= 1.02
                    or not number(tag.get('normalized')) or tag.get('value') not in p):
                raise ValueError('Tag file contains an invalid tag')
    return data


def evaluate(catalog, data):
    """Agreement with the fixture's editorial annotations. A sanity check, not a benchmark:
    the editorial labels were written by the team and cover 36 titles."""
    rows = [(item, data['tags'][item.id]) for item in catalog if item.id in data['tags']]
    if not rows:
        raise ValueError('No tagged titles to evaluate')
    report = {'backend': data['backend'], 'tagged': len(rows), 'failed': len(data.get('failures', {}))}
    if all('mood' in t for _, t in rows):
        hits = [t['mood']['value'] in item.moods for item, t in rows]
        report['mood_hit_at_1'] = round(mean(hits), 3)
        report['mood_mass_on_editorial'] = round(mean(sum(t['mood']['probabilities'][m] for m in item.moods) for item, t in rows), 3)
        report['mood_ece'] = round(expected_calibration_error([t['mood']['answer_confidence'] for _, t in rows], hits), 3)
        report['mood_majority_baseline'] = round(max(mean(m in item.moods for item, _ in rows) for m in MOODS[1:]), 3)
    if all('intensity' in t for _, t in rows):
        report['intensity_mae'] = round(mean(abs(t['intensity']['normalized'] - item.intensity) for item, t in rows), 3)
        report['intensity_constant_baseline_mae'] = round(mean(abs(item.intensity - mean(i.intensity for i, _ in rows)) for item, _ in rows), 3)
    return report


class TaggedDecision:
    """HeuristicDecision with the teacher's soft mood/intensity tags replacing editorial ones.

    Same factor names and weights, so explanations and score bounds are unchanged. Titles without
    tags fall back to the editorial heuristic.
    """

    def __init__(self, data):
        self.tags = data['tags']
        self.fallback = HeuristicDecision()

    def factors(self, item, taste, session):
        factors = self.fallback.factors(item, taste, session)
        tag = self.tags.get(item.id)
        if not tag:
            return factors
        if 'mood' in tag and session.mood != 'any':
            p = tag['mood']['probabilities']
            factors['mood'] = 0.20 * p.get(session.mood, 0) / max(p.values())
        if 'intensity' in tag:
            factors['intensity'] = 0.15 * (1 - abs(tag['intensity']['normalized'] - session.intensity))
        return factors


def backend_from_args(args):
    if not args.url:
        return LexicalBackend()
    key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not key:
        raise SystemExit(f'Environment variable {args.api_key_env} is not set')
    return HttpBackend(args.url, api_key=key, timeout=args.timeout, model=args.model)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Tag the catalogue with a System One teacher')
    parser.add_argument('--catalog', type=Path, default=Path(__file__).parent/'data'/'movies.json')
    parser.add_argument('--url', help='System One server base URL; omit for the offline lexical stand-in')
    parser.add_argument('--api-key-env', help='Name of the environment variable holding a bearer token')
    parser.add_argument('--model', help='Optional model/checkpoint name forwarded to the server')
    parser.add_argument('--timeout', type=float, default=30.0)
    parser.add_argument('--out', type=Path, help='Write tags here')
    parser.add_argument('--evaluate', type=Path, help='Only evaluate an existing tag file')
    args = parser.parse_args(argv)
    catalog = load_catalog(args.catalog)
    if args.evaluate:
        data = load_tags(args.evaluate, catalog)
    else:
        data = tag_catalog(catalog, DecisionClient(backend_from_args(args)))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(data, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(evaluate(catalog, data), indent=2))


if __name__ == '__main__':
    main()
