"""Reproducible smoke/latency report, NOT an accuracy benchmark."""
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from .core import Recommender, Session, load_catalog


def main():
    start = perf_counter()
    catalog = load_catalog(Path(__file__).parent/'data'/'movies.json')
    engine = Recommender(catalog)
    build_ms = (perf_counter()-start)*1000
    feedback = {'m001': 1, 'm004': 1, 'm008': -1}
    report = {'catalog_size': len(catalog), 'build_ms': round(build_ms, 3), 'note': 'Hand-authored demo profile; no relevance judgments or accuracy claims.'}
    for mode in ('baseline', 'session'):
        elapsed = []
        for _ in range(200):
            start = perf_counter()
            rows = engine.recommend(feedback, Session(mood='relaxing', intensity=.2), mode)
            elapsed.append((perf_counter()-start)*1000)
        report[mode] = {'median_ms': round(median(elapsed), 3), 'p95_ms': round(sorted(elapsed)[189], 3),
                        'top_5': [r['content']['title'] for r in rows[:5]],
                        'constraint_violations': sum(r['content']['minutes'] > 120 or r['content']['id'] in feedback for r in rows)}
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
