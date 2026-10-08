"""Taste from public ratings at runtime: item-to-item collaborative filtering and a popularity prior.

Neighbours and popularity are precomputed from a public ratings dataset (flicks/datasets/neighbours.py;
docs/adr/0008-collaborative-filtering.md, docs/adr/0009-popularity-prior.md). Here the user's own likes
and dislikes are only looked up against them, on this device; nothing is sent anywhere and the user's
ratings never influence the shared file.
"""
import json
import math
from pathlib import Path


class ItemNeighbours:
    """{item: [(neighbour, similarity), ...]} restricted to a catalogue, validated on load.

    `popularity` is {item: number of public likes}, empty for files written before it was added.
    """

    FORMAT = 'flicks-neighbours-v1'

    def __init__(self, neighbours, popularity=None):
        self.neighbours = neighbours
        self.popularity = popularity or {}

    @classmethod
    def load(cls, path: Path, catalogue_ids):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('format') != cls.FORMAT or not isinstance(data.get('neighbours'), dict):
            raise ValueError(f'{path} is not a Flicks neighbours file')
        neighbours = {}
        for item, pairs in data['neighbours'].items():
            if item not in catalogue_ids or not isinstance(pairs, list):
                continue  # titles the catalogue no longer has are ignored, not an error
            kept = []
            for pair in pairs:
                if (not isinstance(pair, list) or len(pair) != 2 or pair[0] not in catalogue_ids
                        or type(pair[1]) not in (int, float) or not math.isfinite(pair[1]) or not 0 < pair[1] <= 1):
                    raise ValueError(f'{path} contains an invalid neighbour for {item}')
                kept.append((pair[0], float(pair[1])))
            if kept:
                neighbours[item] = kept
        popularity = data.get('popularity', {})
        if not isinstance(popularity, dict):
            raise ValueError(f'{path} contains invalid popularity')
        for item, likes in popularity.items():
            if type(likes) is not int or likes < 0:
                raise ValueError(f'{path} contains invalid popularity for {item}')
        return cls(neighbours, {item: likes for item, likes in popularity.items() if item in catalogue_ids and likes})

    def __len__(self):
        return len(self.neighbours)

    def get(self, item):
        return self.neighbours.get(item, [])


class CollaborativeTaste:
    """Predicted taste from rated titles' neighbours: Σ sim·rating / Σ sim, in [-1, 1].

    `support` is Σ sim: how much collaborative evidence a title has. A title no rated title points
    to gets no prediction at all.
    """

    def __init__(self, neighbours: ItemNeighbours):
        self.neighbours = neighbours

    def predict(self, feedback):
        """{item: (prediction, support, {rated item: weighted contribution})}."""
        numerator, support, sources = {}, {}, {}
        for rated, value in feedback.items():
            if value not in (1, -1):
                continue
            for item, similarity in self.neighbours.get(rated):
                numerator[item] = numerator.get(item, 0.0) + similarity * value
                support[item] = support.get(item, 0.0) + similarity
                sources.setdefault(item, {})[rated] = similarity * value
        return {item: (numerator[item] / support[item], support[item], sources[item]) for item in numerator}


class HybridTaste:
    """Content taste (TF-IDF) blended per title with collaborative taste, by how much evidence it has.

    weight = support / (support + BLEND): with no collaborative evidence the content score stands;
    with strong evidence the collaborative prediction dominates. Familiarity (which drives the
    discovery factor) stays content-based, because it measures theme distance, not preference.
    """

    # Chosen on development users for the best mean NDCG@10 over profiles of 3 likes, 10 likes and full
    # histories (python -m flicks.datasets.evaluation; docs/evaluation.md). Heavy raters alone would favour
    # 8, but that is 36% worse for a new user with three likes.
    BLEND = 2.0

    def __init__(self, content, neighbours: ItemNeighbours, titles, blend=BLEND):
        self.content = content
        self.collaborative = CollaborativeTaste(neighbours)
        self.titles = titles  # id -> title, for "because you liked …" explanations
        self.blend = blend

    def scores(self, feedback):
        return blend(self.content.scores(feedback), self.collaborative.predict(feedback), self.blend)

    def explain(self, feedback, ids):
        explained = self.content.explain(feedback, ids) if hasattr(self.content, 'explain') else {}
        predictions = self.collaborative.predict(feedback)
        for item in ids:
            sources = predictions.get(item, (0, 0, {}))[2]
            liked = sorted((rated for rated, weight in sources.items() if weight > 0), key=lambda r: -sources[r])
            explained.setdefault(item, {})['because'] = [self.titles[r] for r in liked[:2] if r in self.titles]
        return explained


def blend(content_scores, predictions, strength=HybridTaste.BLEND):
    """Content scores with each predicted title's taste moved toward its collaborative prediction.

    Shared by HybridTaste and the offline evaluation, so both rank exactly the same way.
    """
    scores = dict(content_scores)
    for item, (prediction, support, _) in predictions.items():
        if item in scores:
            weight = support / (support + strength)
            scores[item] = {**scores[item], 'taste': weight * (prediction + 1) / 2 + (1 - weight) * scores[item]['taste']}
    return scores


class PopularityPrior:
    """A taste model that starts from what the public liked most and gives way as the user rates titles.

    taste = w·popularity + (1 - w)·inner taste, with w = strength / (strength + ratings): a new user
    sees widely liked films (the strongest single predictor on held-out MovieLens ratings) and each
    like or pass shifts the ranking toward their own taste. `popular` marks the titles where the prior
    supplied at least half of the taste score, so the interface can say so honestly.

    `covered` is the set of titles the public ratings describe (the film catalogue the file was built
    for). Other titles, such as podcast episodes, keep their own taste: no data is not the same as
    unpopular. None means every title is covered.
    """

    # Chosen on development users for the best mean NDCG@10 over profiles of 3 likes, 10 likes and full
    # histories, on top of the tuned collaborative blend (python -m flicks.datasets.evaluation).
    STRENGTH = 2.0

    def __init__(self, inner, popularity, strength=STRENGTH, covered=None):
        self.inner = inner
        self.popularity = popularity_scores(popularity)
        self.strength = strength
        self.covered = None if covered is None else frozenset(covered)

    def scores(self, feedback):
        return with_prior(self.inner.scores(feedback), self.popularity, feedback, self.strength, self.covered)

    def explain(self, feedback, ids):
        return self.inner.explain(feedback, ids) if hasattr(self.inner, 'explain') else {}


def popularity_scores(likes):
    """{item: public likes} -> {item: score in (0, 1]}, log-scaled so the head does not swamp the rest."""
    top = max(likes.values(), default=0)
    return {item: math.log1p(count) / math.log1p(top) for item, count in likes.items() if count > 0} if top else {}


def with_prior(scores, popularity, feedback, strength=PopularityPrior.STRENGTH, covered=None):
    """Taste scores pulled toward popularity by strength / (strength + number of ratings).

    Titles outside `covered` (when given) are left as they are. Shared by PopularityPrior and the
    offline evaluation, so both rank exactly the same way.
    """
    weight = strength / (strength + sum(1 for value in feedback.values() if value in (1, -1)))
    result = {}
    for item, score in scores.items():
        if covered is not None and item not in covered:
            result[item] = {**score, 'popular': False}
            continue
        prior = weight * popularity.get(item, 0.0)
        personal = (1 - weight) * score['taste']
        result[item] = {**score, 'taste': prior + personal, 'popular': prior > 0 and prior >= personal}
    return result
