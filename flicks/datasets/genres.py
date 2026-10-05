"""Genre vocabulary and genre-based mood/intensity estimates for imported catalogues (films and podcasts).

Public datasets have genres but not the mood and intensity labels the scene reranker uses. These
estimates are a transparent baseline: each genre suggests moods (strongest first) and an intensity,
and a title combines its genres. They are not editorial judgements; System One tagging
(`python -m flicks.tagging`) can replace them with model estimates from each title's description.
"""
from collections import Counter

# MovieLens genre -> the existing catalogue's vocabulary. IMAX is a screen format, not a genre.
GENRE_NAMES = {
    'Action': 'action', 'Adventure': 'adventure', 'Animation': 'animation', 'Children': 'family',
    "Children's": 'family', 'Comedy': 'comedy', 'Crime': 'crime', 'Documentary': 'documentary',
    'Drama': 'drama', 'Fantasy': 'fantasy', 'Film-Noir': 'film-noir', 'Horror': 'horror',
    'Musical': 'musical', 'Mystery': 'mystery', 'Romance': 'romance', 'Sci-Fi': 'science-fiction',
    'Thriller': 'thriller', 'War': 'war', 'Western': 'western',
}

# Apple Podcasts top-level category -> catalogue genre (https://podcasters.apple.com/support/1691-apple-podcasts-categories).
PODCAST_CATEGORIES = {
    'Arts': 'arts', 'Business': 'business', 'Comedy': 'comedy', 'Education': 'education', 'Fiction': 'fiction',
    'Government': 'government', 'Health & Fitness': 'health-and-fitness', 'History': 'history',
    'Kids & Family': 'family', 'Leisure': 'leisure', 'Music': 'music', 'News': 'news',
    'Religion & Spirituality': 'religion-and-spirituality', 'Science': 'science', 'Society & Culture': 'society-and-culture',
    'Sports': 'sports', 'Technology': 'technology', 'True Crime': 'true-crime', 'TV & Film': 'tv-and-film',
}

# genre -> (moods, strongest first; intensity 0-1)
PROFILES = {
    'action': (('tense', 'uplifting'), 0.75),
    'adventure': (('uplifting', 'curious'), 0.55),
    'animation': (('uplifting', 'relaxing'), 0.25),
    'family': (('uplifting', 'relaxing'), 0.2),
    'comedy': (('uplifting', 'relaxing'), 0.3),
    'crime': (('tense', 'reflective'), 0.65),
    'documentary': (('curious', 'reflective'), 0.3),
    'drama': (('reflective',), 0.45),
    'fantasy': (('curious', 'uplifting'), 0.45),
    'film-noir': (('tense', 'reflective'), 0.6),
    'horror': (('tense',), 0.9),
    'musical': (('uplifting', 'relaxing'), 0.25),
    'mystery': (('curious', 'tense'), 0.55),
    'romance': (('uplifting', 'relaxing'), 0.3),
    'science-fiction': (('curious', 'tense'), 0.55),
    'thriller': (('tense',), 0.75),
    'war': (('reflective', 'tense'), 0.8),
    'western': (('tense', 'reflective'), 0.6),
    # Podcast categories (spoken audio is gentler than film at the same subject; True Crime is the exception)
    'arts': (('reflective', 'relaxing'), 0.25),
    'business': (('curious',), 0.35),
    'education': (('curious', 'reflective'), 0.25),
    'fiction': (('curious', 'tense'), 0.5),
    'government': (('curious', 'reflective'), 0.4),
    'health-and-fitness': (('uplifting', 'curious'), 0.3),
    'history': (('curious', 'reflective'), 0.4),
    'leisure': (('relaxing', 'uplifting'), 0.2),
    'music': (('relaxing', 'uplifting'), 0.25),
    'news': (('curious', 'tense'), 0.5),
    'religion-and-spirituality': (('reflective', 'relaxing'), 0.2),
    'science': (('curious',), 0.3),
    'society-and-culture': (('reflective', 'curious'), 0.35),
    'sports': (('uplifting',), 0.55),
    'technology': (('curious',), 0.35),
    'true-crime': (('tense', 'curious'), 0.7),
    'tv-and-film': (('curious', 'uplifting'), 0.35),
}
MOOD_ORDER = ('relaxing', 'uplifting', 'curious', 'tense', 'reflective')  # stable tie-break


def normalize_genres(raw_genres):
    """MovieLens genre names -> catalogue genres, deduplicated, in the original order."""
    return list(dict.fromkeys(GENRE_NAMES[g] for g in raw_genres if g in GENRE_NAMES))


def estimate(genres):
    """(moods, intensity) for a title's catalogue genres.

    Moods: a genre's first mood counts 1, its second 0.5; the top two overall win. Intensity leans
    toward the most intense genre (0.6 * max + 0.4 * mean), so a horror comedy is still intense.
    """
    known = [PROFILES[g] for g in genres if g in PROFILES]
    if not known:
        raise ValueError('No known genres to estimate from')
    votes = Counter()
    for moods, _ in known:
        for weight, mood in zip((1.0, 0.5), moods, strict=False):  # profiles list one or two moods
            votes[mood] += weight
    ranked = sorted(votes, key=lambda mood: (-votes[mood], MOOD_ORDER.index(mood)))
    intensities = [intensity for _, intensity in known]
    intensity = 0.6 * max(intensities) + 0.4 * sum(intensities) / len(intensities)
    return ranked[:2], round(intensity, 2)
