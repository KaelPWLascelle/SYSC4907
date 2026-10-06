"""Precompute item-to-item neighbours from public ratings (build time only; needs NumPy).

    python -m flicks.datasets.neighbours        # writes movielens-small.neighbours.json next to the catalogue

Similarity is adjusted cosine over the users who rated both films: each rating minus that user's mean,
so a harsh rater's 3 and a generous rater's 4 count alike. It is shrunk toward zero when few users
rated both (n / (n + SHRINK)), so two films one person loved do not look identical. Each film keeps
its K most similar catalogue films with positive similarity.

The file also records each film's popularity (how many raters liked it, rating >= LIKE), for the
popularity prior that new users start from (docs/adr/0009-popularity-prior.md).

The app reads the result with flicks/collaborative.py and needs no NumPy. The user's own ratings are
never part of this computation: only the public dataset is (docs/adr/0008-collaborative-filtering.md).
"""
import argparse
from collections import Counter
import csv
from dataclasses import dataclass
import json
from pathlib import Path

from ..collaborative import ItemNeighbours
from ..config import DEFAULT_CATALOG
from ..core import load_catalog

K = 30
SHRINK = 10.0
MIN_CO_RATERS = 2
BLOCK = 1024
DECIMALS = 4
LIKE = 4.0


@dataclass(frozen=True)
class Rating:
    user: str
    item: str
    value: float


def read_ratings(path: Path, prefix='ml'):
    """MovieLens ratings.csv -> Rating records with catalogue-style item IDs ('ml1')."""
    with path.open(encoding='utf-8', newline='') as handle:
        return [Rating(row['userId'], f"{prefix}{row['movieId']}", float(row['rating'])) for row in csv.DictReader(handle)]


def build(ratings, catalogue_ids, k=K, shrink=SHRINK):
    """{item: [(neighbour, similarity), ...]} for catalogue items, strongest first."""
    import numpy as np  # build-time dependency only (pip install -e ".[datasets]")

    users = sorted({r.user for r in ratings})
    items = sorted({r.item for r in ratings} & set(catalogue_ids))
    if not items:
        return {}
    user_index = {u: i for i, u in enumerate(users)}
    item_index = {it: i for i, it in enumerate(items)}
    values = np.zeros((len(users), len(items)), dtype=np.float32)
    rated = np.zeros((len(users), len(items)), dtype=np.float32)
    for r in ratings:
        column = item_index.get(r.item)
        if column is not None:
            values[user_index[r.user], column] = r.value
            rated[user_index[r.user], column] = 1.0
    # Each user's mean over *all* their ratings, not only catalogue films: otherwise trimming the
    # catalogue would shift every user's baseline and silently change every similarity.
    totals, numbers = {}, {}
    for r in ratings:
        totals[r.user] = totals.get(r.user, 0.0) + r.value
        numbers[r.user] = numbers.get(r.user, 0) + 1
    means = np.array([[totals[u] / numbers[u]] for u in users], dtype=np.float32)
    centered = (values - means) * rated            # deviations from each user's mean, 0 where unrated
    squared = centered * centered

    neighbours = {}
    for start in range(0, len(items), BLOCK):
        stop = min(start + BLOCK, len(items))
        dot = centered[:, start:stop].T @ centered                   # Σ c_ui c_uj over co-raters
        norm_i = squared[:, start:stop].T @ rated                    # Σ c_ui² over users who also rated j
        norm_j = rated[:, start:stop].T @ squared                    # Σ c_uj² over users who also rated i
        co_raters = rated[:, start:stop].T @ rated
        with np.errstate(divide='ignore', invalid='ignore'):
            similarity = dot / np.sqrt(norm_i * norm_j) * (co_raters / (co_raters + shrink))
        similarity[~np.isfinite(similarity) | (co_raters < MIN_CO_RATERS)] = 0.0
        for row, item_column in enumerate(range(start, stop)):
            sims = similarity[row]
            sims[item_column] = 0.0                                  # not its own neighbour
            top = np.argpartition(-sims, min(k, len(sims) - 1))[:k]
            # Round before filtering: a similarity of 0.00003 is positive but rounds to 0, which is no neighbour.
            rounded = ((items[j], round(float(sims[j]), DECIMALS)) for j in top)
            ranked = sorted(((j, s) for j, s in rounded if s > 0), key=lambda pair: (-pair[1], pair[0]))
            if ranked:
                neighbours[items[item_column]] = ranked
    return neighbours


def popularity(ratings, catalogue_ids, like=LIKE):
    """{item: number of raters who liked it} for catalogue items with at least one like."""
    return dict(Counter(r.item for r in ratings if r.value >= like and r.item in catalogue_ids))


def sidecar(catalogue: Path) -> Path:
    """Where the app looks for a catalogue's neighbours: movielens-small.json -> movielens-small.neighbours.json."""
    return catalogue.with_suffix('.neighbours.json')


def write(neighbours, path: Path, source: str, catalogue_ids, likes=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    payload = {'format': ItemNeighbours.FORMAT, 'k': K, 'shrink': SHRINK, 'source': source,
               'neighbours': {item: [[j, s] for j, s in pairs] for item, pairs in sorted(neighbours.items())},
               'popularity': dict(sorted((likes or {}).items()))}
    tmp.write_text(json.dumps(payload, separators=(',', ':')) + '\n', encoding='utf-8')
    # Validate against the catalogue, not the items that have neighbours: a film can be someone's
    # neighbour without having enough raters for a list of its own. Never write a file the app would reject.
    ItemNeighbours.load(tmp, catalogue_ids)
    tmp.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Precompute item-to-item neighbours from MovieLens ratings')
    parser.add_argument('--catalog', type=Path, required=True, help='Catalogue the neighbours are for')
    parser.add_argument('--ratings', type=Path, required=True, help='MovieLens ratings.csv')
    args = parser.parse_args(argv)
    if args.catalog == DEFAULT_CATALOG:
        parser.error('the bundled catalogue has no ratings dataset; use an imported catalogue')
    catalogue_ids = {item.id for item in load_catalog(args.catalog)}
    ratings = read_ratings(args.ratings)
    neighbours = build(ratings, catalogue_ids)
    out = sidecar(args.catalog)
    write(neighbours, out, str(args.ratings), catalogue_ids, popularity(ratings, catalogue_ids))
    print(f'{len(neighbours)} of {len(catalogue_ids)} titles have neighbours -> {out}')


if __name__ == '__main__':
    main()
