from pathlib import Path
import tempfile
import unittest

from flicks.core import DEFAULT_MIX, Content, HeuristicDecision, Recommender, Session, load_catalog
from flicks.taste import TasteSummary
from helpers import CATALOG, app_client


def item(key, genres, tags):
    return Content(key, key.title(), 2000, 'movie', 90, genres, tags, ['curious'], 0.5, ' '.join(tags))


class MixTests(unittest.TestCase):
    def test_the_mix_weights_the_factors_and_scores_still_add_up(self):
        catalog = load_catalog(CATALOG)
        engine = Recommender(catalog)
        for mix in (DEFAULT_MIX, (1, 0, 0, 0), (0.25, 0.25, 0.25, 0.25), (0, 0, 0, 1)):
            with self.subTest(mix=mix):
                for pick in engine.recommend({'m001': 1}, Session(mood='curious', mix=mix)):
                    self.assertAlmostEqual(sum(pick['factors'].values()), pick['score'])
                    self.assertLessEqual(pick['score'], 1 + 1e-9)
                    for weight, value in zip(mix, pick['factors'].values(), strict=True):
                        self.assertLessEqual(value, weight + 1e-9)

    def test_taste_only_mix_matches_the_taste_lens(self):
        engine = Recommender(load_catalog(CATALOG))
        tuned = [p['content']['id'] for p in engine.recommend({'m001': 1}, Session(mix=(1, 0, 0, 0)))]
        lens = [p['content']['id'] for p in engine.recommend({'m001': 1}, Session(), 'baseline')]
        self.assertEqual(tuned, lens)

    def test_invalid_mixes_are_refused(self):
        for mix in ((0.5, 0.5), (0.5, 0.5, 0.5, -0.5), (0.3, 0.3, 0.3, 0.3), (float('nan'), 0, 0, 1), 'abcd'):
            with self.subTest(mix=mix), self.assertRaises(ValueError):
                Session(mix=mix)
        self.assertEqual(HeuristicDecision().factors(item('a', ['drama'], ['x']), {'taste': 1, 'familiarity': None},
                                                     Session(mix=(0, 0, 0, 1)))['taste'], 0)


class TasteSummaryTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [item('heist', ['crime'], ['heist', 'caper', 'crime']), item('caper', ['crime'], ['caper', 'twist']),
                        item('space', ['science-fiction'], ['space', 'sci-fi']), item('song', ['musical'], ['songs', 'dance'])]
        self.summary = TasteSummary(self.catalog, Recommender(self.catalog))

    def test_genres_lean_toward_likes_and_away_from_passes(self):
        result = self.summary.summarize({'heist': 1, 'caper': 1, 'song': -1})
        lean = {g['genre']: g['affinity'] for g in result['genres']}
        self.assertEqual(lean, {'crime': 0.5, 'musical': -0.3333})
        self.assertEqual((result['liked'], result['passed']), (2, 1))

    def test_themes_come_from_tags_and_skip_genre_words(self):
        themes = self.summary.summarize({'heist': 1, 'caper': 1, 'space': 1, 'song': -1})['themes']
        liked = [t['term'] for t in themes['liked']]
        self.assertEqual(liked[0], 'caper')  # shared by two liked titles
        self.assertNotIn('crime', liked)     # a genre, shown in the genre chart
        self.assertNotIn('sci-fi', liked)
        self.assertEqual({t['term'] for t in themes['passed']}, {'songs', 'dance'})
        self.assertEqual(max(t['weight'] for t in themes['liked'] + themes['passed']), 1)

    def test_no_ratings_is_an_empty_summary(self):
        result = self.summary.summarize({})
        self.assertEqual((result['genres'], result['themes'], result['influences']), ([], {'liked': [], 'passed': []}, []))


class TasteApiTests(unittest.TestCase):
    def test_taste_and_mix_over_http(self):
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp)) as (client, _):
            for content_id, value in (('m001', 1), ('m004', 1), ('m008', -1)):
                client.post('/api/feedback', json={'id': content_id, 'value': value})
            taste = client.get('/api/taste').json()
            self.assertEqual((taste['liked'], taste['passed']), (2, 1))
            self.assertTrue(taste['genres'] and taste['themes']['liked'])
            tuned = client.post('/api/recommend', json={'session': {'mix': [1, 0, 0, 0]}}).json()['recommendations']
            self.assertEqual({k for p in tuned for k, v in p['factors'].items() if v}, {'taste'})
            self.assertEqual(client.post('/api/recommend', json={'session': {'mix': [1, 1, 0, 0]}}).status_code, 400)
            self.assertEqual(client.post('/api/recommend', json={'session': {'mix': ['1', 0, 0, 0]}}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
