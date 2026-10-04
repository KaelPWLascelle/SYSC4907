import http.client
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from flicks.core import MOODS, Content, HeuristicDecision, Recommender, Session, TfidfTaste, load_catalog
from flicks.store import FeedbackStore
from flicks.__main__ import default_db, make_server, ROOT
from flicks.commands import CommandInterpreter
from unittest import mock


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
    def test_all_moods_are_selectable_in_ui(self):
        class Options(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_mood = False
                self.values = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'select': self.in_mood = attrs.get('id') == 'mood'
                if tag == 'option' and self.in_mood: self.values.append(attrs.get('value'))
            def handle_endtag(self, tag):
                if tag == 'select': self.in_mood = False
        parser = Options()
        parser.feed((ROOT/'static'/'index.html').read_text())
        self.assertEqual(set(parser.values), set(MOODS))

    def test_bundled_catalog(self):
        catalog = load_catalog(ROOT/'data'/'movies.json')
        self.assertEqual(len(catalog), 36)
        self.assertTrue(any(i.minutes < 60 for i in catalog))

    def test_invalid_catalog_rejected(self):
        rows = json.loads((ROOT/'data'/'movies.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.json'
            for payload in ([], [rows[0], rows[0]], [{**rows[0], 'minutes': 0}], [{**rows[0], 'moods': ['invalid']}], [{**rows[0], 'tags': 'not a list'}]):
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError): load_catalog(path)

    def test_persistence_overwrite_clear_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'nested'/'profile.sqlite3'
            store = FeedbackStore(path)
            store.set('movie', 1)
            self.assertEqual(FeedbackStore(path).all(), {'movie': 1})
            store.set('movie', -1)
            self.assertEqual(store.all(), {'movie': -1})
            for value in (True, 2, '1', None):
                with self.assertRaises(ValueError): store.set('movie', value)
            store.set('movie', 0)
            self.assertEqual(store.all(), {})


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = make_server(ROOT/'data'/'movies.json', Path(cls.temp.name)/'test.sqlite3', 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def request(self, path, payload=None, headers=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        body = raw if raw is not None else json.dumps(payload) if payload is not None else None
        request_headers = {'Content-Type': 'application/json', **(headers or {})}
        connection.request('POST' if body is not None else 'GET', path, body, request_headers)
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def test_end_to_end_feedback_and_recommendations(self):
        self.assertEqual(self.request('/api/feedback', {'id': 'm001', 'value': 1})[0], 200)
        state = json.loads(self.request('/api/state')[1])
        self.assertEqual(state['feedback']['m001'], 1)
        response = json.loads(self.request('/api/recommend', {'session': {'minutes': 120}})[1])
        self.assertFalse(response['cold_start'])
        self.assertTrue(response['recommendations'])
        self.assertTrue(all(r['content']['id'] != 'm001' and r['content']['minutes'] <= 120 for r in response['recommendations']))
        self.request('/api/feedback', {'id': 'm001', 'value': 0})

    def test_bad_inputs(self):
        for path, payload in (('/api/feedback', {'id': 'missing', 'value': 1}), ('/api/feedback', {'id': [], 'value': 1}), ('/api/feedback', {'id': 'm001', 'value': True}), ('/api/recommend', {'session': {'minutes': -1}}), ('/api/recommend', {'mode': 'bad'}), ('/api/recommend', {'session': None}), ('/api/recommend', {'session': {'intensity': float('nan')}}), ('/api/recommend', {'extra': 1}), ('/api/recommend', [])):
            with self.subTest(payload=payload): self.assertEqual(self.request(path, payload)[0], 400)
        self.assertEqual(self.request('/api/recommend', raw='{broken')[0], 400)
        self.assertEqual(self.request('/api/recommend', raw='x'*8193)[0], 400)

    def test_origin_host_content_type_and_static_paths(self):
        self.assertEqual(self.request('/api/feedback', {'id': 'm001', 'value': 1}, {'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(self.request('/api/state', headers={'Host': 'other.example'})[0], 403)
        self.assertEqual(self.request('/api/recommend', {}, {'Content-Type': 'text/plain'})[0], 400)
        self.assertEqual(self.request('/../store.py')[0], 404)
        status, body, headers = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'Top picks for this moment', body)
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        for path in ('/app.js', '/style.css', '/poster.js', '/couch-host.js'): self.assertEqual(self.request(path)[0], 200)

class RebrandTests(unittest.TestCase):
    def test_former_name_still_works_as_a_spoken_prefix(self):
        rules = CommandInterpreter(load_catalog(ROOT/'data'/'movies.json'))
        for text in ('Hey Kevin like Arrival', 'Hey Flicks like Arrival', 'flicks like Arrival'):
            with self.subTest(text=text):
                self.assertEqual((rules.parse(text)['intent'], rules.parse(text)['id']), ('feedback', 'm001'))

    def test_ratings_from_before_the_rebrand_are_kept(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(Path, 'home', return_value=Path(home)):
            self.assertEqual(default_db(), Path(home)/'.flicks'/'feedback.sqlite3')
            legacy = Path(home)/'.kevin'/'feedback.sqlite3'
            legacy.parent.mkdir(); legacy.touch()
            self.assertEqual(default_db(), legacy)
            current = Path(home)/'.flicks'/'feedback.sqlite3'
            current.parent.mkdir(); current.touch()
            self.assertEqual(default_db(), current)

if __name__ == '__main__': unittest.main()
