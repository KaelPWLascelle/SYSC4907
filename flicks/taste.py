"""What a profile's ratings say, for the "Your taste" view (docs/adr/0015-your-taste.md).

Everything is derived from the same data the ranking uses (ratings, the catalogue's genres and tags,
and the collaborative "because" links), so the view never claims something the ranking does not use.
"""
from collections import Counter
import math

from .core import Session

PASS_WEIGHT = 0.7      # a pass counts for less than a like, as in the content model's profile
THEMES = 12
INFLUENCE_PICKS = 40   # how many top picks the "films shaping your picks" count looks at


class TasteSummary:
    def __init__(self, catalog, recommender):
        self.by_id = {item.id: item for item in catalog}
        self.recommender = recommender
        genres = {g for item in catalog for g in item.genres}
        # Tags that only restate a genre ("drama", "sci-fi") belong to the genre chart, not the themes.
        self.genre_tags = genres | {g.replace('-', ' ') for g in genres} | {'sci-fi', 'scifi', 'sci fi'}
        frequency = Counter(tag for item in catalog for tag in set(item.tags))
        self.idf = {tag: math.log(len(catalog) / count) for tag, count in frequency.items()}

    def summarize(self, feedback):
        liked = [self.by_id[k] for k, v in sorted(feedback.items()) if v == 1 and k in self.by_id]
        passed = [self.by_id[k] for k, v in sorted(feedback.items()) if v == -1 and k in self.by_id]
        return {'liked': len(liked), 'passed': len(passed), 'genres': self.genres(liked, passed),
                'themes': self.themes(liked, passed), 'influences': self.influences(feedback) if liked else []}

    @staticmethod
    def genres(liked, passed):
        """Per genre: likes, passes, and a lean in (-1, 1), shrunk toward 0 by two pseudo-ratings."""
        counts = {}
        for items, index in ((liked, 0), (passed, 1)):
            for item in items:
                for genre in item.genres:
                    counts.setdefault(genre, [0, 0])[index] += 1
        rows = [{'genre': g, 'liked': up, 'passed': down, 'affinity': round((up - down) / (up + down + 2), 4)}
                for g, (up, down) in counts.items()]
        return sorted(rows, key=lambda g: (-g['affinity'], -g['liked'], g['genre']))

    def themes(self, liked, passed):
        """Tags weighted by rarity (IDF): what the liked titles share, and what the passed ones do."""
        score = Counter()
        for items, sign in ((liked, 1.0), (passed, -PASS_WEIGHT)):
            for item in items:
                for tag in set(item.tags):
                    if tag not in self.genre_tags:
                        score[tag] += sign * self.idf.get(tag, 0.0)
        top = max((abs(v) for v in score.values()), default=0) or 1
        positive = sorted(((t, v) for t, v in score.items() if v > 0), key=lambda kv: (-kv[1], kv[0]))[:THEMES]
        negative = sorted(((t, v) for t, v in score.items() if v < 0), key=lambda kv: (kv[1], kv[0]))[:THEMES]
        return {'liked': [{'term': t, 'weight': round(v / top, 4)} for t, v in positive],
                'passed': [{'term': t, 'weight': round(-v / top, 4)} for t, v in negative]}

    def influences(self, feedback):
        """Liked films, by how many of the top picks name them as the reason ("fans of X also like this")."""
        count = Counter()
        for pick in self.recommender.recommend(feedback, Session(minutes=600), 'baseline', limit=INFLUENCE_PICKS):
            count.update(pick['because'][:2])
        return [{'title': t, 'picks': n} for t, n in sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]
