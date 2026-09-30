"""System One client, catalogue tagging, distillation and command fallback. No network or models."""
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from kevin.__main__ import ROOT, make_server
from kevin.core import Recommender, Session, load_catalog
from kevin.distill import Student, agreement, export_laya, split_of
from kevin.intent import SystemOneInterpreter
from kevin.systemone import (DecisionClient, HttpBackend, LexicalBackend, PrivacyError, SystemOneError, choice,
                             expected_calibration_error, noul, parse_answers, score, validate_questions)
from kevin.tagging import FILM_QUESTIONS, TaggedDecision, evaluate, film_state, load_tags, tag_catalog

# The request/response pair documented in laya's docs/http-api.md (Jev-compatible wire format).
QUESTIONS = {
    'queue': choice('Which team?', {'billing': 'billing and refunds', 'tech': 'login and app issues', 'other': 'everything else'}),
    'urgency': score('How urgent?', ['calm', 'firm', 'angry', 'furious']),
    'human': noul('Does this need a human?'),
}
RESPONSE = {'model': 'laya-rl-agent', 'answers': {
    'queue': {'type': 'choice', 'choice': 'billing', 'probabilities': {'billing': 0.9281, 'tech': 0.0412, 'other': 0.0307},
              'confidence': 0.4534, 'answer_confidence': 0.9281},
    'urgency': {'type': 'score', 'score': 2.6389, 'legend': {'0': 'calm', '1': 'firm', '2': 'angry', '3': 'furious'},
                'probabilities': {'0': 0.0099, '1': 0.0713, '2': 0.536, '3': 0.3828}},
    'human': {'type': 'noul', 'noul': 0.8727, 'confidence': 0.8727, 'answer_confidence': 0.8727}},
    'usage': {'input_tokens': 74, 'output_tokens': 0}}


def mutate(path, value):
    response = json.loads(json.dumps(RESPONSE))
    target = response
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return response


class Canned:
    """Backend stub: returns a fixed wire response and records what it was sent."""
    def __init__(self, response, local=True):
        self.response, self.local, self.name, self.calls = response, local, 'canned', []

    def raw(self, state, questions):
        self.calls.append((state, questions))
        return self.response(state, questions) if callable(self.response) else self.response


class WireFormatTests(unittest.TestCase):
    def test_documented_response_parses(self):
        answers = parse_answers(QUESTIONS, RESPONSE)
        self.assertEqual(answers['queue'].value, 'billing')
        self.assertAlmostEqual(answers['queue'].answer_confidence, .9281, 3)
        self.assertEqual(answers['urgency'].value, '2')
        self.assertAlmostEqual(answers['urgency'].expected, 2.2917, 3)
        self.assertTrue(0 <= answers['urgency'].normalized <= 1)
        self.assertEqual((answers['human'].value, answers['human'].expected), ('true', .8727))

    def test_untrusted_answers_are_rejected(self):
        bad = [mutate(['answers'], []), mutate(['answers', 'queue'], KeyError),
               mutate(['answers', 'extra'], {'type': 'noul', 'noul': .5}),
               mutate(['answers', 'queue', 'type'], 'score'),
               mutate(['answers', 'queue', 'probabilities'], {'billing': .5, 'tech': .1, 'other': .1}),
               mutate(['answers', 'queue', 'probabilities'], {'billing': 1.0, 'invented': 0.0, 'other': 0.0}),
               mutate(['answers', 'queue', 'probabilities', 'tech'], math.nan),
               mutate(['answers', 'queue', 'probabilities', 'tech'], '0.04'),
               mutate(['answers', 'queue', 'choice'], 'other'), mutate(['answers', 'queue', 'choice'], 'invented'),
               mutate(['answers', 'queue', 'choice'], ['billing']),
               mutate(['answers', 'urgency', 'probabilities'], {'0': .5, '1': .5}),
               mutate(['answers', 'human', 'noul'], 1.4), mutate(['answers', 'human', 'noul'], True), None]
        for response in bad:
            with self.subTest(response=response), self.assertRaises(SystemOneError):
                parse_answers(QUESTIONS, response)

    def test_question_validation(self):
        validate_questions(FILM_QUESTIONS)
        for questions in ({}, {'Bad-Id': noul('x')}, {'q': {'type': 'rank', 'instructions': 'x'}},
                          {'q': choice('x', {'only': 'one'})}, {'q': score('x', ['one'])}, {'q': choice('', {'a': '', 'b': ''})},
                          {'q': {'type': 'noul', 'instructions': 'x', 'criteria': {'no': 'a', 'yes': 'b'}}},
                          {f'q{i}': noul('x') for i in range(65)}):
            with self.subTest(questions=questions), self.assertRaises(ValueError):
                validate_questions(questions)

    def test_ece(self):
        self.assertAlmostEqual(expected_calibration_error([.75] * 4, [1, 1, 1, 0]), 0)
        self.assertAlmostEqual(expected_calibration_error([.95] * 4, [1, 0, 0, 0]), .7)
        with self.assertRaises(ValueError): expected_calibration_error([], [])


class HttpBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen = []
        seen = cls.seen

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path, self.headers.get('Authorization'), body))
                status, reply = (500, {'detail': 'inference failed'}) if body['state'] == 'fail' else (200, RESPONSE)
                data = json.dumps(reply).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_speaks_the_systemone_protocol(self):
        client = DecisionClient(HttpBackend(self.url, api_key='secret', model='english'))
        answers = client.decide('I was charged twice', QUESTIONS, private=True)
        path, auth, body = self.seen[-1]
        self.assertEqual((path, auth), ('/v1/systemone', 'Bearer secret'))
        self.assertEqual(body, {'state': 'I was charged twice', 'questions': QUESTIONS, 'model': 'english'})
        self.assertEqual(answers['queue'].value, 'billing')

    def test_local_backend_ignores_environment_proxies(self):
        from unittest import mock
        with mock.patch.dict('os.environ', {'http_proxy': 'http://127.0.0.1:9', 'HTTP_PROXY': 'http://127.0.0.1:9', 'no_proxy': '', 'NO_PROXY': ''}):
            answers = DecisionClient(HttpBackend(self.url)).decide('my private request', QUESTIONS, private=True)
        self.assertEqual(answers['queue'].value, 'billing')  # a proxied request would have hit the dead port

    def test_server_errors_and_unreachable(self):
        with self.assertRaises(SystemOneError):
            HttpBackend(self.url).raw('fail', QUESTIONS)
        with self.assertRaises(SystemOneError):
            HttpBackend('http://127.0.0.1:9', timeout=1).raw('x', QUESTIONS)

    def test_url_rules(self):
        self.assertTrue(HttpBackend('http://localhost:8000').local)
        self.assertTrue(HttpBackend('http://[::1]:8000/v1/systemone').local)
        self.assertFalse(HttpBackend('https://api.typesafe.ai').local)
        for url in ('http://api.typesafe.ai', 'ftp://127.0.0.1', 'localhost:8000', 'http://'):
            with self.subTest(url=url), self.assertRaises(ValueError): HttpBackend(url)


class PrivacyTests(unittest.TestCase):
    def test_user_text_never_reaches_a_remote_backend(self):
        remote = Canned(RESPONSE, local=False)
        with self.assertRaises(PrivacyError):
            DecisionClient(remote).decide('my private request', QUESTIONS, private=True)
        self.assertEqual(remote.calls, [])
        self.assertEqual(DecisionClient(remote).decide('public synopsis', QUESTIONS, private=False)['queue'].value, 'billing')

    def test_assistant_refuses_remote_backend(self):
        catalog = load_catalog(ROOT/'data'/'movies.json')
        with self.assertRaises(PrivacyError):
            SystemOneInterpreter(catalog, DecisionClient(Canned(RESPONSE, local=False)))

    def test_teacher_sees_only_public_fields(self):
        item = load_catalog(ROOT/'data'/'movies.json')[0]
        self.assertEqual(set(film_state(item)), {'title', 'year', 'genres', 'description'})


class TaggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT/'data'/'movies.json')
        cls.data = tag_catalog(cls.catalog, DecisionClient(LexicalBackend()))

    def test_every_title_tagged_and_report(self):
        self.assertEqual(len(self.data['tags']), len(self.catalog))
        report = evaluate(self.catalog, self.data)
        for key in ('mood_hit_at_1', 'mood_ece', 'mood_majority_baseline', 'intensity_mae', 'intensity_constant_baseline_mae'):
            self.assertTrue(0 <= report[key] <= 1, key)

    def test_failures_are_recorded_not_fatal(self):
        good = LexicalBackend()
        flaky = Canned(lambda state, questions: {} if state['title'] == 'Arrival' else good.raw(state, questions))
        data = tag_catalog(self.catalog, DecisionClient(flaky))
        self.assertIn('m001', data['failures'])
        self.assertEqual(len(data['tags']), len(self.catalog) - 1)

    def test_tag_file_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'tags.json'
            path.write_text(json.dumps(self.data))
            self.assertEqual(load_tags(path, self.catalog)['tags'], self.data['tags'])
            for broken in ({**self.data, 'schema_version': 99}, {**self.data, 'tags': {'nope': {}}},
                           {**self.data, 'tags': {'m001': {'mood': {**self.data['tags']['m001']['mood'], 'probabilities': {'relaxing': .2}}}}},
                           {**self.data, 'tags': {'m001': {'mood': {**self.data['tags']['m001']['mood'],
                                                                    'probabilities': {'relaxing': -1, 'uplifting': 2, 'curious': 0, 'tense': 0, 'reflective': 0}}}}},
                           {**self.data, 'tags': {'m001': {'mood': {**self.data['tags']['m001']['mood'], 'normalized': 'high'}}}}):
                path.write_text(json.dumps(broken))
                with self.assertRaises(ValueError): load_tags(path, self.catalog)

    def test_tagged_decision_is_bounded_and_explained(self):
        engine = Recommender(self.catalog, decision=TaggedDecision(self.data))
        for mood in ('any', 'relaxing', 'tense'):
            for row in engine.recommend({'m001': 1}, Session(mood=mood, minutes=600), limit=100):
                self.assertEqual(set(row['factors']), {'taste', 'mood', 'intensity', 'novelty'})
                self.assertAlmostEqual(row['score'], sum(row['factors'].values()))
                self.assertTrue(0 <= row['score'] <= 1)

    def test_soft_mood_uses_probabilities(self):
        item = self.catalog[0]
        data = {'tags': {item.id: {'mood': {'probabilities': {'relaxing': .6, 'tense': .3, 'curious': .1}},
                                   'intensity': {'normalized': .25}}}}
        factors = TaggedDecision(data).factors(item, {'taste': .5, 'familiarity': None}, Session(mood='tense', intensity=.25))
        self.assertAlmostEqual(factors['mood'], .10)
        self.assertAlmostEqual(factors['intensity'], .15)


class DistillTests(unittest.TestCase):
    QUESTIONS = {'mood': choice('Mood?', {'curious': 'space science', 'uplifting': 'funny laugh'}),
                 'kids': noul('Kids?', no='gore', yes='cartoon')}

    def rows(self):
        rows = []
        for i in range(12):
            space = i % 2 == 0
            state = f'film {i} about {"space science stars" if space else "funny laugh jokes"} {"cartoon" if i % 3 else "gore"}'
            rows.append((state, {'mood': {'curious': .9, 'uplifting': .1} if space else {'curious': .1, 'uplifting': .9},
                                 'kids': {'false': .1, 'true': .9} if i % 3 else {'false': .9, 'true': .1}}))
        return rows

    def test_student_learns_teacher_and_serves_wire_format(self):
        student = Student(self.QUESTIONS, dim=512).fit(self.rows())
        client = DecisionClient(student)
        self.assertEqual(client.decide('a space science documentary', self.QUESTIONS, private=True)['mood'].value, 'curious')
        self.assertEqual(client.decide('a funny laugh riot cartoon', self.QUESTIONS, private=True)['kids'].value, 'true')
        restored = Student.from_json(json.loads(json.dumps(student.to_json())))
        state = 'space jokes cartoon'
        before, after = student.raw(state, self.QUESTIONS)['answers'], restored.raw(state, self.QUESTIONS)['answers']
        self.assertAlmostEqual(before['kids']['noul'], after['kids']['noul'], 4)  # weights stored to 6 d.p.
        for option, p in before['mood']['probabilities'].items():
            self.assertAlmostEqual(p, after['mood']['probabilities'][option], 4)
        with self.assertRaises(ValueError): student.raw(state, {'other': noul('x')})

    def test_browser_parity_fixture_matches_python(self):
        from kevin.distill import features
        from kevin.systemone import options
        fixture = json.loads((Path(__file__).parent/'fixtures'/'student-parity.json').read_text())
        student = Student.from_json(fixture['model'])
        self.assertTrue(any(isinstance(c['state'], dict) for c in fixture['cases']))
        for case in fixture['cases']:
            x = features(case['state'], student.dim)
            for qid, expected in case['probabilities'].items():
                got = dict(zip(options(student.questions[qid]), student.distribution(qid, x)))
                for option, p in expected.items():
                    self.assertAlmostEqual(got[option], p, 12)

    def test_laya_export_splits_are_disjoint_and_complete(self):
        catalog = load_catalog(ROOT/'data'/'movies.json')
        data = tag_catalog(catalog, DecisionClient(LexicalBackend()))
        with tempfile.TemporaryDirectory() as folder:
            counts = export_laya(catalog, data, folder)
            self.assertEqual(sum(counts.values()), len(catalog))
            seen = set()
            for name in ('train', 'dev', 'test'):
                for line in (Path(folder)/f'{name}.jsonl').read_text().splitlines():
                    row = json.loads(line)
                    self.assertEqual(split_of(row['id']), name)
                    self.assertEqual(set(row['gold']), set(row['questions']))
                    self.assertNotIn('moods', json.loads(row['state']))
                    seen.add(row['id'])
            self.assertEqual(len(seen), len(catalog))
        report = agreement(Student(data['questions'], 256), catalog, data, 'test')
        self.assertEqual(report['decisions'], counts['test'] * len(data['questions']))


class InterpreterTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(ROOT/'data'/'movies.json')
        self.parser = SystemOneInterpreter(self.catalog, DecisionClient(LexicalBackend()))

    def test_rules_still_win(self):
        self.assertEqual(self.parser.parse('relaxing, 90 minutes')['parser'], 'rules')
        self.assertEqual(self.parser.parse('Like Arrival')['intent'], 'feedback')

    def test_model_fills_gaps_rules_do_not_cover(self):
        result = self.parser.parse('something cozy and soothing tonight')
        self.assertEqual((result['intent'], result['parser'], result['patch']), ('session', 'systemone', {'mood': 'relaxing'}))
        result = self.parser.parse('skip the horror stuff tonight')
        self.assertEqual(result['patch'], {'excluded_genres': ['horror']})

    def test_model_never_overrides_a_deliberate_refusal(self):
        always_relaxing = Canned(lambda s, q: {'answers': {k: {'type': 'choice', 'probabilities': {o: float(o == 'relaxing') for o in v['criteria']}}
                                                            if v['type'] == 'choice' else {'type': 'noul', 'noul': 1.0} for k, v in q.items()}})
        parser = SystemOneInterpreter(self.catalog, DecisionClient(always_relaxing))
        for text in ('not relaxing', 'relaxing and tense', 'like it', '90.5 minutes'):
            with self.subTest(text=text): self.assertEqual(parser.parse(text)['intent'], 'unknown')
        self.assertEqual(always_relaxing.calls, [])

    def test_low_confidence_and_outage_change_nothing(self):
        self.assertEqual(self.parser.parse('whatever you think')['intent'], 'unknown')
        down = SystemOneInterpreter(self.catalog, DecisionClient(Canned(lambda s, q: (_ for _ in ()).throw(SystemOneError('down')))))
        self.assertIn('unavailable', down.parse('something cozy')['note'])

    def test_api_uses_the_assistant(self):
        import http.client
        with tempfile.TemporaryDirectory() as folder:
            server = make_server(ROOT/'data'/'movies.json', Path(folder)/'p.sqlite3', 0, system_one=DecisionClient(LexicalBackend()))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                body = json.dumps({'text': 'something cozy and soothing', 'session': asdict(Session())})
                conn.request('POST', '/api/command/apply', body, {'Content-Type': 'application/json', 'Host': f'127.0.0.1:{server.server_port}'})
                reply = json.loads(conn.getresponse().read())
                self.assertEqual(reply['session']['mood'], 'relaxing')
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
