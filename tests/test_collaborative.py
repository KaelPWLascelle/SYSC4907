import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

from flicks.collaborative import (
    CollaborativeTaste,
    HybridTaste,
    ItemNeighbours,
    PopularityPrior,
    blend,
    popularity_scores,
    with_prior,
)
from flicks.core import Content, Recommender, Session
from flicks.datasets import evaluation
from flicks.datasets.neighbours import Rating, popularity
from helpers import app_client

HAS_NUMPY = importlib.util.find_spec('numpy') is not None
NEIGHBOURS = ItemNeighbours({
    'a': [('b', 0.8), ('c', 0.2)],
    'd': [('b', 0.4), ('c', 0.6)],
})


def item(key):
    return Content(key, key.upper(), 2000, 'movie', 90, ['drama'], ['quiet'], ['curious'], 0.5, f'About {key}')


class StubContent:
    """Content taste of 0.5 everywhere, so the collaborative part is visible on its own."""

    def scores(self, feedback):
        return {key: {'taste': 0.5, 'familiarity': None} for key in 'abcde'}

    def explain(self, feedback, ids):
        return {key: {'evidence': ['quiet'], 'negative_evidence': []} for key in ids}


class PredictionTests(unittest.TestCase):
    def test_prediction_is_similarity_weighted_mean_of_ratings(self):
        predictions = CollaborativeTaste(NEIGHBOURS).predict({'a': 1, 'd': -1})
        prediction, support, sources = predictions['b']
        self.assertAlmostEqual(prediction, (0.8 - 0.4) / (0.8 + 0.4))
        self.assertAlmostEqual(support, 1.2)
        self.assertEqual(sources, {'a': 0.8, 'd': -0.4})
        self.assertAlmostEqual(predictions['c'][0], (0.2 - 0.6) / 0.8)
        self.assertNotIn('e', predictions)  # nothing rated points to it

    def test_blend_moves_taste_toward_the_prediction_by_support(self):
        content = {'b': {'taste': 0.5, 'familiarity': None}, 'e': {'taste': 0.3, 'familiarity': 0.1}}
        blended = blend(content, {'b': (1.0, 1.0, {})}, strength=1.0)
        self.assertAlmostEqual(blended['b']['taste'], 0.5 * 1.0 + 0.5 * 0.5)  # weight 1 / (1 + 1)
        self.assertEqual(blended['e'], content['e'])                        # no evidence: content stands
        self.assertEqual(content['b']['taste'], 0.5)                        # input not mutated

    def test_explanations_name_the_liked_titles_that_contributed(self):
        hybrid = HybridTaste(StubContent(), NEIGHBOURS, {'a': 'Alpha', 'd': 'Delta'})
        explained = hybrid.explain({'a': 1, 'd': 1}, ['b', 'c', 'e'])
        self.assertEqual(explained['b']['because'], ['Alpha', 'Delta'])  # strongest first
        self.assertEqual(explained['c']['because'], ['Delta', 'Alpha'])
        self.assertEqual(explained['e']['because'], [])
        self.assertEqual(explained['b']['evidence'], ['quiet'])          # content evidence kept
        passed = hybrid.explain({'a': -1}, ['b'])
        self.assertEqual(passed['b']['because'], [])                     # a pass is never a "because"

    def test_recommendations_carry_the_explanation(self):
        catalog = [item(key) for key in 'abcde']
        hybrid = HybridTaste(StubContent(), NEIGHBOURS, {i.id: i.title for i in catalog}, blend=1.0)
        top = Recommender(catalog, taste=hybrid).recommend({'a': 1}, Session(), 'baseline')
        self.assertEqual(top[0]['content']['id'], 'b')
        self.assertEqual(top[0]['because'], ['A'])
        self.assertTrue(math.isclose(sum(top[0]['factors'].values()), top[0]['score']))


class PopularityPriorTests(unittest.TestCase):
    def test_popularity_is_log_scaled_to_the_most_liked_title(self):
        scores = popularity_scores({'a': 99, 'b': 9, 'c': 0})
        self.assertEqual(scores['a'], 1.0)
        self.assertAlmostEqual(scores['b'], math.log(10) / math.log(100))
        self.assertNotIn('c', scores)
        self.assertEqual(popularity_scores({}), {})

    def test_prior_gives_way_as_the_user_rates_titles(self):
        content = {'a': {'taste': 0.5, 'familiarity': None}, 'b': {'taste': 0.9, 'familiarity': 0.2}}
        prior = {'a': 1.0}
        new = with_prior(content, prior, {}, strength=2.0)              # no ratings: popularity alone
        self.assertEqual((new['a']['taste'], new['b']['taste']), (1.0, 0.0))
        self.assertEqual((new['a']['popular'], new['b']['popular']), (True, False))
        rated = with_prior(content, prior, {'x': 1, 'y': -1}, strength=2.0)  # a pass counts as a rating
        self.assertAlmostEqual(rated['a']['taste'], 0.5 * 1.0 + 0.5 * 0.5)
        self.assertAlmostEqual(rated['b']['taste'], 0.5 * 0.9)
        self.assertEqual(rated['b']['familiarity'], 0.2)                     # only taste changes
        settled = with_prior(content, prior, {str(n): 1 for n in range(18)}, strength=2.0)
        self.assertAlmostEqual(settled['a']['taste'], 0.1 * 1.0 + 0.9 * 0.5)
        self.assertFalse(settled['a']['popular'])                           # mostly the user's own taste now
        self.assertEqual(with_prior(content, prior, {'x': 0}, strength=2.0), new)  # not a like or a pass

    def test_new_users_start_from_the_most_liked_titles(self):
        catalog = [item(key) for key in 'abcde']
        taste = PopularityPrior(HybridTaste(StubContent(), NEIGHBOURS, {}), {'c': 50, 'e': 5}, strength=1.0)
        top = Recommender(catalog, taste=taste).recommend({}, Session(), 'baseline')
        self.assertEqual([p['content']['id'] for p in top[:2]], ['c', 'e'])
        self.assertTrue(top[0]['popular'])
        self.assertEqual(top[0]['evidence'], ['quiet'])                     # the inner model still explains
        liked = Recommender(catalog, taste=taste).recommend({'a': 1, 'd': 1}, Session(), 'baseline')
        self.assertFalse(next(p for p in liked if p['content']['id'] == 'c')['popular'])  # own taste outweighs it now


class NeighbourFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'n.json'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, neighbours, fmt=ItemNeighbours.FORMAT, **extra):
        self.path.write_text(json.dumps({'format': fmt, 'neighbours': neighbours, **extra}), encoding='utf-8')

    def test_loads_and_ignores_titles_no_longer_in_the_catalogue(self):
        self.write({'a': [['b', 0.5]], 'gone': [['b', 0.5]]})
        loaded = ItemNeighbours.load(self.path, {'a', 'b'})
        self.assertEqual((len(loaded), loaded.get('a'), loaded.get('gone')), (1, [('b', 0.5)], []))

    def test_loads_popularity_when_present(self):
        self.write({'a': [['b', 0.5]]}, popularity={'a': 3, 'b': 0, 'gone': 9})
        self.assertEqual(ItemNeighbours.load(self.path, {'a', 'b'}).popularity, {'a': 3})
        self.write({'a': [['b', 0.5]]})                                      # files from before popularity
        self.assertEqual(ItemNeighbours.load(self.path, {'a', 'b'}).popularity, {})
        for bad in ([3], {'a': -1}, {'a': 1.5}, {'a': True}, {'a': '3'}):
            with self.subTest(popularity=bad):
                self.write({'a': [['b', 0.5]]}, popularity=bad)
                with self.assertRaises(ValueError):
                    ItemNeighbours.load(self.path, {'a', 'b'})

    def test_rejects_malformed_files(self):
        for neighbours, fmt in (({'a': [['b', 0.5]]}, 'other'), ({'a': [['b', 0]]}, None), ({'a': [['b', 1.5]]}, None),
                                ({'a': [['b', 'x']]}, None), ({'a': [['zzz', 0.5]]}, None), ({'a': [['b']]}, None)):
            with self.subTest(neighbours=neighbours, fmt=fmt):
                self.write(neighbours, fmt or ItemNeighbours.FORMAT)
                with self.assertRaises(ValueError):
                    ItemNeighbours.load(self.path, {'a', 'b'})


@unittest.skipUnless(HAS_NUMPY, 'the datasets extra (NumPy) is not installed')
class BuildTests(unittest.TestCase):
    def ratings(self):
        # Users 1-3 like x and y together; user 4 rated only x. z is rated by one user with x.
        rows = [('1', 'x', 5), ('1', 'y', 5), ('1', 'w', 1), ('2', 'x', 4), ('2', 'y', 5), ('2', 'w', 2),
                ('3', 'x', 5), ('3', 'y', 4), ('3', 'w', 1), ('4', 'x', 3), ('5', 'x', 5), ('5', 'z', 5), ('5', 'w', 1)]
        return [Rating(u, i, float(v)) for u, i, v in rows]

    def test_similar_items_are_neighbours_with_shrinkage(self):
        from flicks.datasets.neighbours import build
        neighbours = build(self.ratings(), {'x', 'y', 'z', 'w'}, k=5, shrink=10.0)
        x = dict(neighbours['x'])
        self.assertIn('y', x)
        self.assertNotIn('x', x)                    # never its own neighbour
        self.assertNotIn('z', x)                    # only one co-rater: below MIN_CO_RATERS
        self.assertNotIn('w', x)                    # rated low when x is rated high: negative, dropped
        self.assertLess(x['y'], 1.0)                # shrunk: three co-raters is not certainty
        self.assertAlmostEqual(x['y'], dict(neighbours['y'])['x'])  # symmetric

    def test_similarities_that_round_to_zero_are_dropped(self):
        from flicks.datasets import neighbours as module
        original = module.DECIMALS
        module.DECIMALS = 0  # every similarity below 0.5 now rounds to 0
        try:
            built = module.build(self.ratings(), {'x', 'y', 'z', 'w'}, k=5, shrink=10.0)
        finally:
            module.DECIMALS = original
        self.assertTrue(all(s > 0 for pairs in built.values() for _, s in pairs))

    def test_restricted_to_the_catalogue_and_round_trips_through_the_file(self):
        from flicks.datasets.neighbours import build, sidecar, write
        neighbours = build(self.ratings(), {'x', 'y'})
        self.assertEqual(set(neighbours), {'x', 'y'})
        likes = popularity(self.ratings(), {'x', 'y'})
        with tempfile.TemporaryDirectory() as folder:
            catalogue = Path(folder)/'cat.json'
            self.assertEqual(sidecar(catalogue).name, 'cat.neighbours.json')
            write(neighbours, sidecar(catalogue), 'test', {'x', 'y', 'unrated'}, likes)
            loaded = ItemNeighbours.load(sidecar(catalogue), {'x', 'y'})
            self.assertEqual((loaded.get('x'), loaded.popularity), (neighbours['x'], likes))


class PopularityCountTests(unittest.TestCase):
    def test_counts_likes_of_catalogue_titles_only(self):
        ratings = [Rating('1', 'x', 5.0), Rating('2', 'x', 4.0), Rating('3', 'x', 3.5), Rating('1', 'y', 2.0),
                   Rating('1', 'gone', 5.0)]
        self.assertEqual(popularity(ratings, {'x', 'y'}), {'x': 2})


class EvaluationTests(unittest.TestCase):
    def test_split_holds_out_one_liked_film_and_removes_it_from_training(self):
        ratings = [Rating(u, f'i{n}', 5.0 if n < 6 else 1.0) for u in ('u1', 'u2', 'u3') for n in range(8)]
        ratings.append(Rating('u4', 'i0', 5.0))  # too few likes to evaluate
        development, test, training = evaluation.split(ratings, {f'i{n}' for n in range(8)})
        cases = development + test
        self.assertEqual(sorted(c.user for c in cases), ['u1', 'u2', 'u3'])
        for case in cases:
            self.assertNotIn(case.held_out, case.feedback)
            self.assertIn(case.held_out, case.rated)
            self.assertEqual({v for v in case.feedback.values()}, {1, -1})
            self.assertNotIn((case.user, case.held_out), {(r.user, r.item) for r in training})  # no leakage
        self.assertEqual(len(training), len(ratings) - 3)
        self.assertEqual(evaluation.split(ratings, {f'i{n}' for n in range(8)})[:2], (development, test))  # deterministic

    def test_ranks_count_ties_as_half_and_metrics_use_the_cutoff(self):
        scores = {'held': 0.5, 'a': 0.9, 'b': 0.5, 'c': 0.5, 'd': 0.1}
        self.assertEqual(evaluation.rank_of('held', scores, ['held', 'a', 'b', 'c', 'd']), 3.0)
        self.assertEqual(evaluation.metrics([1, 11]), {'hit_rate_at_10': 0.5, 'ndcg_at_10': 0.5, 'hit_rate_ci95': 0.693})


class ApiTests(unittest.TestCase):
    def test_state_reports_collaborative_mode_and_picks_explain_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'n.json'
            path.write_text(json.dumps({'format': ItemNeighbours.FORMAT, 'neighbours': {'m001': [['m004', 0.9]]}}),
                            encoding='utf-8')
            with app_client(Path(folder), neighbours=path) as (client, services):
                self.assertTrue(client.get('/api/state').json()['collaborative'])
                client.post('/api/feedback', json={'id': 'm001', 'value': 1})
                picks = client.post('/api/recommend', json={'session': {'minutes': 200}, 'mode': 'baseline'}).json()['recommendations']
                moon = next(p for p in picks if p['content']['id'] == 'm004')
                self.assertEqual(moon['because'], ['Arrival'])
                self.assertFalse(services.popularity_prior)                  # no popularity in this file
            with app_client(Path(folder)/'plain') as (client, _):
                self.assertFalse(client.get('/api/state').json()['collaborative'])

    def test_a_new_user_is_shown_the_most_liked_titles_first(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'n.json'
            path.write_text(json.dumps({'format': ItemNeighbours.FORMAT, 'neighbours': {'m001': [['m004', 0.9]]},
                                        'popularity': {'m004': 40, 'm001': 2}}), encoding='utf-8')
            with app_client(Path(folder), neighbours=path) as (client, services):
                self.assertTrue(services.popularity_prior)
                picks = client.post('/api/recommend', json={'session': {'minutes': 200}, 'mode': 'baseline'}).json()['recommendations']
                self.assertEqual((picks[0]['content']['id'], picks[0]['popular']), ('m004', True))
                self.assertFalse(picks[-1]['popular'])


if __name__ == '__main__':
    unittest.main()
