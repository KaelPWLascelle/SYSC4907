"""Ask Flicks agent check: a fixed set of requests the rules cannot read, scored against what a person meant.

    python -m flicks.assistant.agent_eval --llm-url http://127.0.0.1:11434 --model qwen3.5:4b
    python -m flicks.assistant.agent_eval --no-llm    # the shipped rules + student, for comparison

Each case passes when the agent's proposal has the expected intent and the expected key fields. The set is
small and team-written, so it shows whether a model is usable, not a precise accuracy. None of these
phrasings appear in the agent's prompt examples.
"""
import argparse
import json
import statistics
import time

from ..config import DEFAULT_CATALOG
from ..core import load_catalog
from ..search import TitleIndex
from .agent import AgentInterpreter
from .ask_student import Student, StudentInterpreter
from .commands import CommandInterpreter
from .llm import LocalChat

CASES = [
    ('a film like the martian but lighter', {'intent': 'search', 'similar': 'm003'}),
    ('more in the vein of that slow alien language one', {'intent': 'search'}),
    ('put on that one about the guy stranded on mars', {'intent': 'play', 'id': 'm003'}),
    ('something to watch with my kids that is not too long', {'intent': 'session'}),
    ('i want to see something i would never normally pick', {'intent': 'session', 'novelty_at_least': 0.7}),
    ('honestly just need to decompress, keep it mellow', {'intent': 'session', 'mood': 'relaxing'}),
    ('i want my heart pounding', {'intent': 'session', 'intensity_at_least': 0.7}),
    ('make me laugh, i had a rough day', {'intent': ('session', 'search')}),
    ('how do i bake bread', {'intent': 'unknown'}),
    ('what time is it in tokyo', {'intent': 'unknown'}),
]


def passed(result, expected):
    intents = expected['intent'] if isinstance(expected['intent'], tuple) else (expected['intent'],)
    if result['intent'] not in intents:
        return False
    patch = result.get('patch') or {}
    checks = {'similar': result.get('similar'), 'id': result.get('id'), 'mood': patch.get('mood')}
    if any(key in expected and checks[key] != expected[key] for key in checks):
        return False
    if 'novelty_at_least' in expected and patch.get('novelty', 0) < expected['novelty_at_least']:
        return False
    return not ('intensity_at_least' in expected and patch.get('intensity', 0) < expected['intensity_at_least'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--llm-url', default='http://127.0.0.1:11434')
    parser.add_argument('--model', default='qwen3.5:4b')
    parser.add_argument('--no-llm', action='store_true', help='Score the default Ask pipeline (rules, then the student)')
    args = parser.parse_args(argv)
    catalog = load_catalog(DEFAULT_CATALOG)
    titles = TitleIndex(catalog)
    rules = CommandInterpreter(catalog, titles)
    if args.no_llm:
        agent, args.model = StudentInterpreter(rules, Student.load(), catalog, titles, lambda _: True), 'rules + student'
    else:
        agent = AgentInterpreter(rules, LocalChat(args.llm_url, args.model, timeout=180), catalog, titles)
    rows, latencies = [], []
    for text, expected in CASES:
        start = time.perf_counter()
        result = agent.parse(text)
        latencies.append(time.perf_counter() - start)
        rows.append({'text': text, 'pass': passed(result, expected), 'intent': result['intent'],
                     'summary': result['summary'], 'seconds': round(latencies[-1], 4)})
    report = {'model': args.model, 'passed': sum(r['pass'] for r in rows), 'cases': len(rows),
              'median_seconds': round(statistics.median(latencies), 4), 'max_seconds': round(max(latencies), 4), 'rows': rows}
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
