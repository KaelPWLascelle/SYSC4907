"""Latency and memory benchmark: how fast each part of Flicks answers, in process and over HTTP.

    python -m flicks.benchmark [--out report.json] [--repeat 200]

It measures speed, not quality (recommendation quality is `python -m flicks.datasets.evaluation`; the
Ask student's accuracy is `python -m flicks.datasets.ask --evaluate-only`). Every catalogue available is
measured: the bundled 36 titles always, and the MovieLens import when it has been built
(`python -m flicks.datasets.movielens`). Each figure is the median and 95th percentile of `--repeat`
calls after one warm-up, on fixed inputs, with the database in a temporary folder. Results are machine
dependent; the report records the machine.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

from .config import DEFAULT_CATALOG, HOME, Settings
from .core import Session

MOVIELENS = HOME/'catalogs'/'movielens-small.json'
SCENE = Session(mood='relaxing', minutes=120, intensity=0.2)
REQUESTS = ['long week, i want to switch off, nothing scary', 'funny films from the 90s', 'Like Arrival',
            'something like the martian but lighter', 'what is the weather']


def timed(fn, repeat):
    fn()  # warm-up: caches, imports, first allocations
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {'median_ms': round(statistics.median(samples), 3), 'p95_ms': round(samples[int(len(samples) * 0.95) - 1], 3)}


def peak_rss_mb():
    """Peak resident memory of this process (macOS reports bytes, Linux kilobytes); None elsewhere."""
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024 if sys.platform == 'darwin' else 1024), 1)


@contextmanager
def app(catalog):
    from fastapi.testclient import TestClient

    from .api.app import create_app
    from .services import build_services
    neighbours = catalog.with_suffix('.neighbours.json')
    with tempfile.TemporaryDirectory() as temp:
        settings = Settings(db=Path(temp)/'bench.sqlite3', catalog=catalog,
                            neighbours=neighbours if neighbours.is_file() else None, static_dir=Path(temp)/'static')
        start = time.perf_counter()
        services = build_services(settings, speech=_NoSpeech())
        startup = (time.perf_counter() - start) * 1000
        with TestClient(create_app(settings, services), base_url=f'http://127.0.0.1:{settings.port}') as client:
            yield services, client, startup


class _NoSpeech:
    def status(self):
        return {'available': False, 'message': 'not benchmarked'}


def bench_catalog(catalog, repeat):
    with app(catalog) as (svc, client, startup):
        titles = {item.title: item.id for item in svc.catalog}
        liked = [titles[t] for t in ('Arrival', 'Moon', 'The Martian', 'Toy Story') if t in titles] or [svc.catalog[0].id]
        many = {item.id: (1 if i % 3 else -1) for i, item in enumerate(svc.catalog[:40])}
        few = {liked[0]: 1, **({liked[1]: 1} if len(liked) > 1 else {})}
        for content_id, value in few.items():
            svc.ratings.set(content_id, value)
        report = {'catalog': str(catalog), 'titles': len(svc.catalog), 'collaborative': svc.collaborative,
                  'startup_ms': round(startup, 1)}
        stages = {
            'recommend, no ratings': lambda: svc.recommender.recommend({}, SCENE),
            'recommend, 2 ratings': lambda: svc.recommender.recommend(few, SCENE),
            'recommend, 40 ratings': lambda: svc.recommender.recommend(many, SCENE),
            'explain one pick': lambda: svc.recommender.explain_item(few, SCENE, svc.catalog[-1].id),
            'taste summary (40 ratings)': lambda: svc.taste.summarize(many),
            'search "funny films from the 90s"': lambda: svc.titles.search('funny films from the 90s'),
        }
        for text in REQUESTS:
            stages[f'ask: "{text}"'] = lambda text=text: svc.interpreter.parse(text)
        report['in_process'] = {name: timed(fn, repeat) for name, fn in stages.items()}
        endpoints = {
            'GET /api/state': lambda: client.get('/api/state'),
            'POST /api/recommend': lambda: client.post('/api/recommend', json={'session': {'mood': 'relaxing'}}),
            'GET /api/titles?q=': lambda: client.get('/api/titles', params={'q': 'funny films from the 90s'}),
            'POST /api/command/preview': lambda: client.post('/api/command/preview', json={'text': REQUESTS[0]}),
            'GET /api/taste': lambda: client.get('/api/taste'),
            'POST /api/explain': lambda: client.post('/api/explain', json={'id': svc.catalog[-1].id}),
        }
        for name, fn in endpoints.items():
            assert fn().status_code == 200, name
        report['http'] = {name: timed(fn, max(20, repeat // 4)) for name, fn in endpoints.items()}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, help='Also write the report as JSON')
    parser.add_argument('--repeat', type=int, default=200)
    args = parser.parse_args(argv)
    catalogs = [DEFAULT_CATALOG] + ([MOVIELENS] if MOVIELENS.is_file() else [])
    report = {'machine': {'platform': platform.platform(), 'processor': platform.processor() or platform.machine(),
                         'python': platform.python_version(), 'cpus': os.cpu_count()},
              'catalogues': [bench_catalog(c, args.repeat) for c in catalogs]}
    report['peak_memory_mb'] = peak_rss_mb()
    for result in report['catalogues']:
        print(f"\n{result['titles']:,} titles ({'content + collaborative' if result['collaborative'] else 'content'}), "
              f"startup {result['startup_ms']:,.0f} ms")
        for group in ('in_process', 'http'):
            for name, value in result[group].items():
                print(f"  {group:10} {name:52} {value['median_ms']:9.2f} ms  p95 {value['p95_ms']:9.2f} ms")
    print(f"\nPeak memory: {report['peak_memory_mb']} MB")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
