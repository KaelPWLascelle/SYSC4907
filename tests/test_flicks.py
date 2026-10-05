import json
import math
from pathlib import Path
import tempfile
import unittest

from flicks.commands import CommandInterpreter
from flicks.core import Content, HeuristicDecision, Recommender, Session, load_catalog
from flicks.db import Database
from flicks.repositories import RatingsRepository
from helpers import CATALOG, app_client


def item(key, tags, minutes=90, mood='curious', intensity=.5):
    return Content(key, key, 2000, 'movie', minutes, tags, tags, [mood], intensity, ' '.join(tags))


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [item('seed', ['space', 'science']), item('related', ['space', 'science']),
                        item('different', ['romance', 'family']), item('horror', ['horror', 'gore'], mood='tense', intensity=1)]
        self.engine = Recommender(self.catalog)

    def test_likes_promote_related_content(self):
        result = self.engine.recommend({'seed': 1}, Session(), 'baseline')
        self.assertEqual(result[0]['content']['id'], 'related')
        self.assertAlmostEqual(result[0]['score'], 1)
        self.assertTrue(result[0]['evidence'])

    def test_dislikes_demote_related_content(self):
        scores = self.engine.taste.scores({'seed': -1})
        self.assertLess(scores['related']['taste'], scores['different']['taste'])

    def test_signed_profile_and_unknown_feedback(self):
        scores = self.engine.taste.scores({'seed': 1, 'horror': -1, 'removed': 1})
        self.assertGreater(scores['related']['taste'], scores['horror']['taste'])
        self.assertEqual(scores, self.engine.taste.scores({'seed': 1, 'horror': -1}))

    def test_time_and_feedback_are_hard_constraints_in_both_modes(self):
        for mode in ('baseline', 'session'):
            result = self.engine.recommend({'seed': 1, 'horror': -1}, Session(minutes=90), mode)
            self.assertEqual({r['content']['id'] for r in result}, {'related', 'different'})
            self.assertEqual(self.engine.recommend({}, Session(minutes=89), mode), [])

    def test_mood_changes_ranking_without_changing_taste(self):
        engine = Recommender([item('a', ['same'], mood='relaxing'), item('b', ['same'], mood='tense')])
        self.assertEqual(engine.recommend({}, Session(mood='tense'))[0]['content']['id'], 'b')
        self.assertEqual(engine.recommend({}, Session(mood='relaxing'))[0]['content']['id'], 'a')
        self.assertEqual(engine.recommend({}, Session(mood='tense'), 'baseline')[0]['content']['id'], 'a')

    def test_intensity_and_novelty_direction(self):
        layer = HeuristicDecision()
        taste = {'taste': .5, 'familiarity': .9}
        gentle = item('a', ['same'], intensity=.1)
        self.assertGreater(layer.factors(gentle, taste, Session(intensity=.1))['intensity'], layer.factors(gentle, taste, Session(intensity=.9))['intensity'])
        self.assertGreater(layer.factors(gentle, taste, Session(novelty=.1))['novelty'], layer.factors(gentle, taste, Session(novelty=.9))['novelty'])

    def test_cold_start_neutral_novelty_and_deterministic_ties(self):
        first = self.engine.recommend({}, Session())
        self.assertEqual(first, self.engine.recommend({}, Session()))
        for row in first:
            self.assertEqual(row['familiarity'], None)
            self.assertEqual(row['factors']['taste'], .275)
            self.assertEqual(row['factors']['novelty'], .05)

    def test_explanations_add_up_and_scores_are_bounded(self):
        for row in self.engine.recommend({'seed': 1, 'horror': -1}, Session()):
            self.assertAlmostEqual(row['score'], sum(row['factors'].values()))
            self.assertTrue(0 <= row['score'] <= 1)

    def test_empty_and_all_rated_catalog(self):
        self.assertEqual(Recommender([]).recommend({}, Session()), [])
        self.assertEqual(self.engine.recommend({i.id: 1 for i in self.catalog}, Session()), [])

    def test_session_validation(self):
        for kwargs in ({'mood': 'bad'}, {'minutes': 0}, {'minutes': True}, {'minutes': 5.5}, {'minutes': 601}, {'novelty': math.nan}, {'intensity': math.inf}, {'novelty': True}, {'intensity': -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): Session(**kwargs)

    def test_replaceable_decision_layer(self):
        class Fixed:
            def factors(self, item, taste, session): return {'adapter': .25}
        result = Recommender(self.catalog, decision=Fixed()).recommend({}, Session())
        self.assertTrue(all(r['score'] == .25 for r in result))


class DataTests(unittest.TestCase):
    def test_bundled_catalog(self):
        catalog = load_catalog(CATALOG)
        self.assertEqual(len(catalog), 36)
        self.assertTrue(any(i.minutes < 60 for i in catalog))

    def test_invalid_catalog_rejected(self):
        rows = json.loads((CATALOG).read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.json'
            for payload in ([], [rows[0], rows[0]], [{**rows[0], 'minutes': 0}], [{**rows[0], 'moods': ['invalid']}], [{**rows[0], 'tags': 'not a list'}]):
                path.write_text(json.dumps(payload), encoding='utf-8')
                with self.assertRaises(ValueError): load_catalog(path)

    def test_persistence_overwrite_clear_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'nested'/'profile.sqlite3'
            store = RatingsRepository(Database(path))
            store.set('movie', 1)
            self.assertEqual(RatingsRepository(Database(path)).all(), {'movie': 1})
            store.set('movie', -1)
            self.assertEqual(store.all(), {'movie': -1})
            for value in (True, 2, '1', None):
                with self.assertRaises(ValueError): store.set('movie', value)
            store.set('movie', 0)
            self.assertEqual(store.all(), {})


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = app_client(Path(self.temp.name))
        self.client, self.services = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_end_to_end_feedback_and_recommendations(self):
        self.assertEqual(self.client.post('/api/feedback', json={'id': 'm001', 'value': 1}).status_code, 200)
        self.assertEqual(self.client.get('/api/state').json()['feedback']['m001'], 1)
        response = self.client.post('/api/recommend', json={'session': {'minutes': 120}}).json()
        self.assertFalse(response['cold_start'])
        self.assertTrue(response['recommendations'])
        self.assertTrue(all(r['content']['id'] != 'm001' and r['content']['minutes'] <= 120 for r in response['recommendations']))

    def test_explanations_add_up_over_http(self):
        for row in self.client.post('/api/recommend', json={'session': {'mood': 'relaxing', 'intensity': 0.2}}).json()['recommendations']:
            self.assertTrue(math.isclose(sum(row['factors'].values()), row['score']))

    def test_bad_inputs_are_400_with_a_message(self):
        for path, payload in (('/api/feedback', {'id': 'missing', 'value': 1}), ('/api/feedback', {'id': [], 'value': 1}),
                              ('/api/feedback', {'id': 'm001', 'value': True}), ('/api/feedback', {'id': 'm001', 'value': 2}),
                              ('/api/recommend', {'session': {'minutes': -1}}), ('/api/recommend', {'mode': 'bad'}),
                              ('/api/recommend', {'session': None}), ('/api/recommend', {'session': {'minutes': '90'}}),
                              ('/api/recommend', {'extra': 1}), ('/api/recommend', [])):
            with self.subTest(path=path, payload=payload):
                response = self.client.post(path, json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json()['error'])
        nan = self.client.post('/api/recommend', content='{"session": {"intensity": NaN}}', headers={'Content-Type': 'application/json'})
        self.assertEqual(nan.status_code, 400)
        broken = self.client.post('/api/recommend', content='{broken', headers={'Content-Type': 'application/json'})
        self.assertEqual(broken.status_code, 400)

    def test_transport_rules(self):
        self.assertEqual(self.client.post('/api/feedback', json={'id': 'm001', 'value': 1}, headers={'Origin': 'https://other.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/state', headers={'Host': 'other.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/recommend', content='{}', headers={'Content-Type': 'text/plain'}).status_code, 415)
        self.assertEqual(self.client.post('/api/recommend', content='x' * 8193, headers={'Content-Type': 'application/json'}).status_code, 413)

    def test_frontend_is_served_with_security_headers(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn("default-src 'self'", page.headers['content-security-policy'])
        self.assertEqual(page.headers['cache-control'], 'no-store')
        asset = self.client.get('/assets/app-1234.js')
        self.assertEqual((asset.status_code, asset.headers['cache-control']), (200, 'public, max-age=31536000, immutable'))
        self.assertEqual(self.client.get('/manifest.webmanifest').status_code, 200)
        for path in ('/../config.py', '/couch.html', '/flicks.sqlite3', '/assets/../index.html', '/app.js'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class WakeWordTests(unittest.TestCase):
    def test_the_app_name_is_an_optional_spoken_prefix(self):
        rules = CommandInterpreter(load_catalog(CATALOG))
        for text in ('Hey Flicks like Arrival', 'flicks like Arrival', 'like Arrival'):
            with self.subTest(text=text):
                self.assertEqual((rules.parse(text)['intent'], rules.parse(text)['id']), ('feedback', 'm001'))


if __name__ == '__main__': unittest.main()
