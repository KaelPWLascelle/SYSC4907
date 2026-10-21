"""Discover and "Pick for me": two ways to find a film without searching (docs/adr/0016-discover.md).

The Discover feed interleaves three streams, so it neither repeats Home's top picks nor wanders at random:
- for you: the scene's own ranking;
- something new: the same ranking with discovery turned up, favouring films unlike the ones rated;
- wildcard: the best film in genres the profile has neither rated nor been shown in this feed.
Every item says which stream it came from. Rated titles and titles already shown are skipped, so each
like or pass the client saves reshapes the next page. An item's media is a preview of the film itself
when it plays here (a local file or a stream), and its trailer's video ID when it has one; the client
embeds the trailer only once the viewer allows online trailers. With neither, the card shows the poster
and description, which works offline. Online, films with a trailer are preferred.

"Pick for me" draws one title at random, from the top picks (better-ranked ones likelier) or from anything
the scene allows (uniformly), and reports the chance it had, so even a random pick is explained.
"""
from dataclasses import replace
import math
import random

FOR_YOU, NEW, WILDCARD = 'for_you', 'new', 'wildcard'
PATTERN = (FOR_YOU, NEW, FOR_YOU, WILDCARD, FOR_YOU, NEW)
# Something new: the scene's mood and intensity still count, but discovery leads.
NEW_MIX = (0.35, 0.15, 0.10, 0.40)
NEW_NOVELTY = 0.9
LOOKAHEAD = 12      # how far down a stream to look for a film with something to play
PICK_POOL = 12
# Weights 1/sqrt(rank): the top pick has about a 1 in 6 chance and the 12th about 1 in 20, so better
# matches come up more often without the draw collapsing onto the top pick (score gaps vary too much
# between profiles to weight by score).


class Discover:
    def __init__(self, recommender, media_kind, trailers):
        """media_kind(id): 'file', 'stream' or None. trailers: a TrailerIndex."""
        self.recommender = recommender
        self.media_kind = media_kind
        self.trailers = trailers

    @staticmethod
    def scene(session):
        """Discover is for films, at any length: the scene's mood, intensity and mix still apply."""
        return replace(session, medium='watch', minutes=max(session.minutes, 600), playable=False)

    def media(self, content_id):
        """{'kind': 'file' | 'stream' | None (a preview of the film itself), 'trailer': a YouTube ID or None}."""
        return {'kind': self.media_kind(content_id), 'trailer': self.trailers.get(content_id)}

    def _watchable(self, content_id, online):
        media = self.media(content_id)
        return bool(media['kind'] or (online and media['trailer']))

    def feed(self, feedback, session, seen=(), *, online=False, limit=8):
        recommender = self.recommender
        base = self.scene(session)
        scores = recommender.taste.scores(feedback)
        streams = {
            FOR_YOU: recommender.rank(feedback, base, scores=scores),
            NEW: recommender.rank(feedback, replace(base, novelty=NEW_NOVELTY, mix=NEW_MIX), scores=scores),
        }
        streams[WILDCARD] = streams[NEW]  # filtered by genre when drawn, against what has been shown so far
        by_id = recommender.by_id
        taken = set(seen)
        known = {g for key in list(feedback) + list(seen) if key in by_id for g in by_id[key].genres}
        chosen = []
        for slot in range(limit * len(PATTERN)):
            if len(chosen) == limit:
                break
            stream = PATTERN[slot % len(PATTERN)]
            row = self._draw(streams[stream], taken, known if stream == WILDCARD else None, online)
            if row is None:
                continue
            taken.add(row[1])
            known.update(row[2].genres)
            chosen.append((stream, row))
        picks = recommender.picks(feedback, [row for _, row in chosen], scores)
        return [{**pick, 'stream': stream, 'why': self._why(stream, pick, feedback, by_id),
                 'media': self.media(pick['content']['id'])}
                for (stream, _), pick in zip(chosen, picks, strict=True)]

    def _draw(self, ranked, taken, known_genres, online):
        """The stream's best unshown row, preferring one with something to play among the next LOOKAHEAD."""
        fresh = (row for row in ranked if row[1] not in taken
                 and (known_genres is None or not known_genres.intersection(row[2].genres)))
        window = []
        for row in fresh:
            window.append(row)
            if self._watchable(row[1], online) or len(window) == LOOKAHEAD:
                break
        if not window:
            return None
        return next((row for row in window if self._watchable(row[1], online)), window[0])

    @staticmethod
    def _why(stream, pick, feedback, by_id):
        if stream == FOR_YOU:
            because = pick['because'][:2]  # titles of liked films whose fans rate this highly
            if because:
                return f"Fans of {' and '.join(because)} rate this highly"
            evidence = pick['evidence'][:2]  # what it shares with the films liked
            return f"Your taste: {' · '.join(evidence)}" if evidence else 'A top pick for this scene'
        if stream == NEW:
            return 'Something new: unlike what you usually rate' if feedback else 'Something new to try'
        genres = ', '.join(pick['content']['genres'][:2])
        return f'Wildcard: {genres}, which you haven’t rated yet'

    def pick(self, feedback, session, pool='picks', rng=None):
        """One title at random, with the chance it had: {'pick', 'chance', 'pool'}."""
        rng = rng or random.SystemRandom()
        scores = self.recommender.taste.scores(feedback)
        ranked = self.recommender.rank(feedback, session, scores=scores)
        if not ranked:
            raise ValueError('Nothing fits this scene. Try more time or fewer limits.')
        if pool == 'picks':
            ranked = ranked[:PICK_POOL]
            weights = [1 / math.sqrt(rank) for rank in range(1, len(ranked) + 1)]
        elif pool == 'anything':
            weights = [1.0] * len(ranked)
        else:
            raise ValueError('Unknown pool')
        index = rng.choices(range(len(ranked)), weights=weights)[0]
        pick = self.recommender.picks(feedback, [ranked[index]], scores)[0]
        return {'pick': pick, 'chance': weights[index] / sum(weights), 'pool': len(ranked)}
