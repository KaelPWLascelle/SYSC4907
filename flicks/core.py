"""Pure domain logic. No network, persistence or UI dependencies."""
from collections import Counter
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
from typing import Protocol

STOP_WORDS = frozenset(['a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'her', 'his', 'in', 'into', 'is', 'it', 'its', 'of', 'on', 'or', 'that', 'the', 'their', 'them', 'they', 'this', 'to', 'two', 'while', 'who', 'with'])

MOODS = ('any', 'relaxing', 'uplifting', 'curious', 'tense', 'reflective')
# What the scene asks for: anything, something to watch, or something to listen to (podcast episodes).
MEDIUMS = ('any', 'watch', 'listen')
AUDIO_KINDS = frozenset({'episode'})

@dataclass(frozen=True)
class Content:
    id: str
    title: str
    year: int
    kind: str
    minutes: int
    genres: list[str]
    tags: list[str]
    moods: list[str]
    intensity: float
    description: str
    series: str | None = None  # the show a podcast episode belongs to

    @property
    def audio(self):
        return self.kind in AUDIO_KINDS


def load_catalog(path: Path) -> list[Content]:
    rows = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(rows, list) or not rows:
        raise ValueError('Catalogue must be a nonempty JSON array')
    result, ids = [], set()
    for row in rows:
        item = Content(**row)
        if not isinstance(item.id, str) or not item.id or item.id in ids:
            raise ValueError('Content IDs must be unique nonempty strings')
        for value in (item.title, item.kind, item.description):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Title, kind and description must be nonempty text')
        if type(item.minutes) is not int or item.minutes <= 0 or type(item.year) is not int:
            raise ValueError('Year and positive runtime must be integers')
        if type(item.intensity) not in (float, int) or not math.isfinite(item.intensity) or not 0 <= item.intensity <= 1:
            raise ValueError('Intensity must be finite and between 0 and 1')
        for values in (item.genres, item.tags, item.moods):
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError('Genres, tags and moods must be nonempty text arrays')
        if any(m not in MOODS[1:] for m in item.moods):
            raise ValueError('Unknown catalogue mood')
        if item.series is not None and (not isinstance(item.series, str) or not item.series.strip()):
            raise ValueError('Series must be nonempty text when present')
        ids.add(item.id)
        result.append(item)
    return result

@dataclass(frozen=True)
class Session:
    mood: str = 'any'
    minutes: int = 120
    intensity: float = 0.5
    novelty: float = 0.3
    excluded_genres: tuple[str, ...] = ()
    medium: str = 'any'

    def __post_init__(self):
        if not isinstance(self.excluded_genres, (list, tuple)) or len(self.excluded_genres) > 20 or any(not isinstance(g, str) or not g.strip() or len(g) > 50 for g in self.excluded_genres):
            raise ValueError('Excluded genres must be a list of at most 20 genre names')
        object.__setattr__(self, 'excluded_genres', tuple(sorted(set(self.excluded_genres))))
        if self.mood not in MOODS:
            raise ValueError('Unknown mood')
        if self.medium not in MEDIUMS:
            raise ValueError('Medium must be any, watch or listen')
        if type(self.minutes) is not int or not 1 <= self.minutes <= 600:
            raise ValueError('Available time must be an integer from 1 to 600')
        for value in (self.intensity, self.novelty):
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Intensity and novelty must be finite numbers from 0 to 1')


def unit(vector):
    norm = math.sqrt(sum(v*v for v in vector.values()))
    return {k: v/norm for k, v in vector.items()} if norm else {}


def dot(a, b):
    return sum(v*b.get(k, 0) for k, v in a.items())


class TasteModel(Protocol):
    """Per-title taste in [0, 1] and familiarity in [0, 1] or None for a set of ratings.

    A model may also return `evidence` and `negative_evidence` term lists from `scores`, or provide a
    separate `explain(feedback, ids)` so the (usually costlier) evidence is built only for the titles
    actually shown.
    """
    def scores(self, feedback: dict[str, int]) -> dict[str, dict]: ...


class DecisionLayer(Protocol):
    def factors(self, item: Content, taste: dict, session: Session) -> dict[str, float]: ...


class TfidfTaste:
    """Smoothed IDF, sublinear term frequency, L2-normalized sparse vectors."""
    def __init__(self, catalog):
        self.catalog = catalog
        counts = {}
        for item in catalog:
            # Repeating curated features emphasizes genre/theme over synopsis wording.
            text = ' '.join(item.genres*3 + item.tags*2 + [item.description]).lower()
            counts[item.id] = Counter(t for t in re.findall(r'[a-z0-9]+', text) if t not in STOP_WORDS)
        df = Counter(term for row in counts.values() for term in row)
        self.vectors = {key: unit({t: (1+math.log(n))*(1+math.log((1+len(catalog))/(1+df[t])))
                                  for t, n in row.items()}) for key, row in counts.items()}

    def _profile(self, feedback):
        """(liked centroid, signed profile): the unit vectors every score is a cosine against."""
        def centroid(sign):
            total = Counter()
            for key, value in feedback.items():
                if value == sign and key in self.vectors:
                    total.update(self.vectors[key])
            return unit(total)
        positive, negative = centroid(1), centroid(-1)
        profile = unit({t: positive.get(t, 0)-0.7*negative.get(t, 0) for t in positive.keys() | negative.keys()})
        return positive, profile

    def scores(self, feedback):
        positive, profile = self._profile(feedback)
        return {key: dict(taste=(dot(vector, profile)+1)/2 if profile else 0.5,
                          familiarity=dot(vector, positive) if positive else None)
                for key, vector in self.vectors.items()}

    def explain(self, feedback, ids):
        """The terms that raised (`evidence`) or lowered (`negative_evidence`) each title's taste score."""
        _, profile = self._profile(feedback)
        result = {}
        for key in ids:
            contributions = sorted(((t, v*profile.get(t, 0)) for t, v in self.vectors[key].items()), key=lambda x: -x[1])
            result[key] = dict(evidence=[t for t, value in contributions if value > 0][:4],
                               negative_evidence=[t for t, value in reversed(contributions) if value < 0][:4])
        return result


class HeuristicDecision:
    def factors(self, item, taste, session):
        familiarity = taste['familiarity']
        return {
            'taste': 0.55*taste['taste'],
            'mood': 0.20*(0.5 if session.mood == 'any' else float(session.mood in item.moods)),
            'intensity': 0.15*(1-abs(item.intensity-session.intensity)),
            'novelty': 0.10*(0.5 if familiarity is None else 1-abs((1-familiarity)-session.novelty)),
        }


class Recommender:
    # Picks per show: one podcast's episodes often score alike (same genres and moods), and a row of
    # six episodes of one show is not a set of recommendations.
    MAX_PER_SERIES = 2

    def __init__(self, catalog, taste: TasteModel | None = None, decision: DecisionLayer | None = None):
        self.catalog = catalog
        self.taste = taste or TfidfTaste(catalog)
        self.decision = decision or HeuristicDecision()
        self.genres = frozenset(g for item in catalog for g in item.genres)

    def recommend(self, feedback, session, mode='session', limit=12):
        if mode not in ('session', 'baseline'):
            raise ValueError('Unknown ranking mode')
        if set(session.excluded_genres) - self.genres:
            raise ValueError('Unknown excluded genre for this catalogue')
        scores = self.taste.scores(feedback)
        excluded = set(session.excluded_genres)
        ranked = []
        for item in self.catalog:
            # Hard constraints belong to the application, never to a future model.
            if item.id in feedback or item.minutes > session.minutes or excluded.intersection(item.genres):
                continue
            if (session.medium == 'watch' and item.audio) or (session.medium == 'listen' and not item.audio):
                continue
            taste = scores[item.id]
            factors = self.decision.factors(item, taste, session) if mode == 'session' else {'taste': taste['taste']}
            ranked.append((-sum(factors.values()), item.id, item, factors))
        ranked.sort(key=lambda row: (row[0], row[1]))
        ranked = self._cap_series(ranked)
        if session.medium == 'any':
            ranked = self._alternate_media(ranked)
        top = ranked[:limit]
        # Evidence is the costly part of a score, so it is built only for the titles returned.
        explain = getattr(self.taste, 'explain', None)
        explained = explain(feedback, [row[1] for row in top]) if explain else {}
        result = []
        for negative_score, key, item, factors in top:
            taste = {**scores[key], **explained.get(key, {})}
            result.append(dict(content=asdict(item), score=-negative_score, factors=factors,
                               evidence=taste.get('evidence', []), negative_evidence=taste.get('negative_evidence', []),
                               because=taste.get('because', []), popular=taste.get('popular', False),
                               familiarity=taste['familiarity']))
        return result

    @classmethod
    def _cap_series(cls, ranked):
        """Drop a show's episodes beyond its best MAX_PER_SERIES; films (no series) are never capped."""
        kept, per_series = [], Counter()
        for row in ranked:
            series = row[2].series
            if series is None or per_series[series] < cls.MAX_PER_SERIES:
                per_series[series] += 1
                kept.append(row)
        return kept

    @staticmethod
    def _alternate_media(ranked):
        """For "either": the best films and the best episodes in turn, led by whichever ranks higher.

        Film and episode scores rest on different evidence (public popularity and collaborative patterns
        exist for films only), so they are compared within each medium, not across them.
        """
        video = [row for row in ranked if not row[2].audio]
        audio = [row for row in ranked if row[2].audio]
        if not video or not audio:
            return ranked
        first, second = (video, audio) if (video[0][0], video[0][1]) <= (audio[0][0], audio[0][1]) else (audio, video)
        merged = [row for pair in zip(first, second, strict=False) for row in pair]
        return merged + first[len(second):] + second[len(first):]
