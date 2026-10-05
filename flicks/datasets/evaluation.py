"""Offline evaluation of recommendation quality on MovieLens: leave-one-out, without leakage.

    python -m flicks.datasets.evaluation        # needs the MovieLens catalogue and the [datasets] extra

Protocol (docs/evaluation.md):
- Users with at least MIN_LIKES liked catalogue films (rating >= LIKE) are evaluated. One liked film
  per user is held out at random (fixed seed). The rest become Flicks-style feedback: >= LIKE is a
  like, <= DISLIKE a pass, anything between is ignored (Flicks has no neutral rating).
- Each model ranks every catalogue film the user has not rated, plus the held-out film. Hit rate@10
  and NDCG@10 measure where the held-out film lands. A sampled variant (the held-out film among 100
  random unrated films) is reported for comparison with the literature; it is optimistic.
- Neighbours are rebuilt from the ratings **minus every held-out rating**, so no model sees the answer.
- Users are split in half by a hash of their ID: the blend strength is chosen on the development half
  and every reported number comes from the test half.
- Each model is also evaluated as a new user would be, with only 3 or 10 of the user's likes. The
  blend is tuned for the mean over these profile sizes, because Flicks' own users start with few.
"""
import argparse
from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

from ..collaborative import CollaborativeTaste, ItemNeighbours, blend
from ..config import HOME
from ..core import TfidfTaste, load_catalog
from . import neighbours as neighbour_builder

LIKE, DISLIKE = 4.0, 2.0
MIN_LIKES = 5
CUTOFF = 10
SAMPLED_NEGATIVES = 100
SEED = 4907
BLEND_GRID = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
PROFILE_SIZES = (3, 10, None)  # None: the user's full history


@dataclass(frozen=True)
class Case:
    user: str
    held_out: str
    feedback: dict      # Flicks-style profile without the held-out film
    rated: frozenset    # everything the user rated, including the held-out film


def _hash(text):
    return int(hashlib.sha1(text.encode()).hexdigest(), 16)


def split(ratings, catalogue_ids, seed=SEED):
    """(development cases, test cases, training ratings without any held-out rating)."""
    by_user = {}
    for r in ratings:
        if r.item in catalogue_ids:
            by_user.setdefault(r.user, []).append(r)
    development, test, held = [], [], set()
    for user, rows in sorted(by_user.items()):
        liked = sorted(r.item for r in rows if r.value >= LIKE)
        if len(liked) < MIN_LIKES:
            continue
        held_out = random.Random(f'{seed}:{user}').choice(liked)
        feedback = {r.item: 1 if r.value >= LIKE else -1 for r in rows
                    if r.item != held_out and (r.value >= LIKE or r.value <= DISLIKE)}
        case = Case(user, held_out, feedback, frozenset(r.item for r in rows))
        (development if _hash(user) % 2 == 0 else test).append(case)
        held.add((user, held_out))
    training = [r for r in ratings if (r.user, r.item) not in held]
    return development, test, training


def rank_of(held_out, scores, candidates):
    """1-based rank of the held-out film; ties count half, the expected rank under random tie-breaking."""
    target = scores.get(held_out, 0.0)
    better = sum(1 for c in candidates if c != held_out and scores.get(c, 0.0) > target)
    ties = sum(1 for c in candidates if c != held_out and scores.get(c, 0.0) == target)
    return 1 + better + ties / 2


def metrics(ranks):
    """Hit rate and NDCG at the cutoff, with a 95% interval for the hit rate (normal approximation)."""
    hits = [rank <= CUTOFF for rank in ranks]
    ndcg = [1 / math.log2(rank + 1) if rank <= CUTOFF else 0.0 for rank in ranks]
    rate = statistics.mean(hits)
    return {'hit_rate_at_10': round(rate, 4), 'ndcg_at_10': round(statistics.mean(ndcg), 4),
            'hit_rate_ci95': round(1.96 * math.sqrt(rate * (1 - rate) / len(hits)), 4)}


def evaluate(cases, score_fn, catalogue_ids, seed=SEED):
    """{metric: value} over cases; `score_fn(case) -> {item: score}` (higher is better)."""
    full, sampled = [], []
    universe = sorted(catalogue_ids)
    for case in cases:
        scores = score_fn(case)
        candidates = [item for item in universe if item not in case.rated or item == case.held_out]
        full.append(rank_of(case.held_out, scores, candidates))
        negatives = random.Random(f'{seed}:sample:{case.user}').sample(
            [c for c in candidates if c != case.held_out], SAMPLED_NEGATIVES)
        sampled.append(rank_of(case.held_out, scores, [case.held_out, *negatives]))
    result = metrics(full)
    sampled_metrics = metrics(sampled)
    return {**result, 'sampled_hit_rate_at_10': sampled_metrics['hit_rate_at_10'],
            'sampled_ndcg_at_10': sampled_metrics['ndcg_at_10'], 'users': len(cases)}


def truncate(case, size):
    """The case as a newer user would look: `size` of its likes (chosen with a fixed seed), no passes."""
    if size is None:
        return case
    likes = sorted(item for item, value in case.feedback.items() if value == 1)
    keep = random.Random(f'{SEED}:profile:{size}:{case.user}').sample(likes, min(size, len(likes)))
    return replace(case, feedback={item: 1 for item in keep})


def _label(size):
    return 'full history' if size is None else f'{size} likes'


def run(catalog_path, ratings_path, log=print):
    catalog = load_catalog(catalog_path)
    ids = {item.id for item in catalog}
    development, test, training = split(neighbour_builder.read_ratings(ratings_path), ids)
    log(f'{len(development)} development and {len(test)} test users; rebuilding neighbours without held-out ratings')
    neighbours = ItemNeighbours(neighbour_builder.build(training, ids))
    content_model, collaborative = TfidfTaste(catalog), CollaborativeTaste(neighbours)
    popularity = Counter(r.item for r in training if r.value >= LIKE)
    cache = {}

    def parts(case):
        """Content scores and collaborative predictions, computed once per profile and shared by every model."""
        key = (case.user, tuple(sorted(case.feedback.items())))
        if key not in cache:
            cache[key] = (content_model.scores(case.feedback), collaborative.predict(case.feedback))
        return cache[key]

    def random_scores(case):
        rng = random.Random(f'{SEED}:{case.user}')
        return {item: rng.random() for item in sorted(ids)}

    def hybrid(strength):
        return lambda case: {item: s['taste'] for item, s in blend(*parts(case), strength).items()}

    # Tune for the users Flicks expects (new ones with a few likes, and established ones): the blend
    # strength with the best mean NDCG@10 over every profile size, on development users only.
    log('Choosing the blend strength on development users')
    tuning = {}
    for strength in BLEND_GRID:
        per_size = [evaluate([truncate(c, size) for c in development], hybrid(strength), ids)['ndcg_at_10']
                    for size in PROFILE_SIZES]
        tuning[strength] = round(statistics.mean(per_size), 4)
    best = max(BLEND_GRID, key=lambda strength: (tuning[strength], -strength))
    log(f'  mean NDCG@10 by strength: {tuning} -> {best}')

    models = {
        'random': random_scores,
        'popularity': lambda case: dict(popularity),
        'content (TF-IDF)': lambda case: {item: s['taste'] for item, s in parts(case)[0].items()},
        'collaborative (item-item)': lambda case: {item: p * support for item, (p, support, _) in parts(case)[1].items()},
        f'hybrid (blend {best})': hybrid(best),
    }
    results = {}
    for size in PROFILE_SIZES:
        cases = [truncate(c, size) for c in test]
        log(f'Evaluating on test users ({_label(size)})')
        results[_label(size)] = {name: evaluate(cases, score_fn, ids) for name, score_fn in models.items()}
    return {'protocol': {'like': LIKE, 'dislike': DISLIKE, 'min_likes': MIN_LIKES, 'cutoff': CUTOFF,
                         'sampled_negatives': SAMPLED_NEGATIVES, 'seed': SEED, 'profile_sizes': [_label(s) for s in PROFILE_SIZES],
                         'development_users': len(development), 'test_users': len(test)},
            'blend_tuning_mean_ndcg_at_10': {str(k): v for k, v in tuning.items()}, 'blend': best, 'results': results}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Leave-one-out evaluation of Flicks recommenders on MovieLens')
    parser.add_argument('--catalog', type=Path, default=HOME/'catalogs'/'movielens-small.json')
    parser.add_argument('--ratings', type=Path, default=HOME/'datasets'/'ml-latest-small'/'ratings.csv')
    parser.add_argument('--out', type=Path, help='Also write the report as JSON')
    args = parser.parse_args(argv)
    report = run(args.catalog, args.ratings)
    for profile, rows in report['results'].items():
        print(f"\nTest users, {profile}")
        print(f"{'Model':<28} {'HR@10':>14} {'NDCG@10':>8} {'HR@10 (sampled)':>16}")
        for name, r in rows.items():
            hit = f"{r['hit_rate_at_10']:.3f} ± {r['hit_rate_ci95']:.3f}"
            print(f"{name:<28} {hit:>14} {r['ndcg_at_10']:>8.3f} {r['sampled_hit_rate_at_10']:>16.3f}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
