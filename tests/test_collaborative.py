import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

from flicks.collaborative import CollaborativeTaste, HybridTaste, ItemNeighbours, blend
from flicks.core import Content, Recommender, Session
from flicks.datasets import evaluation
from flicks.datasets.neighbours import Rating
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


class NeighbourFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'n.json'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, neighbours, fmt=ItemNeighbours.FORMAT):
        self.path.write_text(json.dumps({'format': fmt, 'neighbours': neighbours}), encoding='utf-8')

    def test_loads_and_ignores_titles_no_longer_in_the_catalogue(self):
        self.write({'a': [['b', 0.5]], 'gone': [['b', 0.5]]})
        loaded = ItemNeighbours.load(self.path, {'a', 'b'})
        self.assertEqual((len(loaded), loaded.get('a'), loaded.get('gone')), (1, [('b', 0.5)], []))

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
        with tempfile.TemporaryDirectory() as folder:
            catalogue = Path(folder)/'cat.json'
            self.assertEqual(sidecar(catalogue).name, 'cat.neighbours.json')
            write(neighbours, sidecar(catalogue), 'test', {'x', 'y', 'unrated'})
            self.assertEqual(ItemNeighbours.load(sidecar(catalogue), {'x', 'y'}).get('x'), neighbours['x'])


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
            with app_client(Path(folder), neighbours=path) as (client, _):
                self.assertTrue(client.get('/api/state').json()['collaborative'])
                client.post('/api/feedback', json={'id': 'm001', 'value': 1})
                picks = client.post('/api/recommend', json={'session': {'minutes': 200}, 'mode': 'baseline'}).json()['recommendations']
                moon = next(p for p in picks if p['content']['id'] == 'm004')
                self.assertEqual(moon['because'], ['Arrival'])
            with app_client(Path(folder)/'plain') as (client, _):
                self.assertFalse(client.get('/api/state').json()['collaborative'])


if __name__ == '__main__':
    unittest.main()
