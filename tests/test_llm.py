import json
from pathlib import Path
import tempfile
import unittest

from flicks.assistant.agent import AgentInterpreter
from flicks.assistant.commands import CommandInterpreter
from flicks.assistant.llm import LLMError, LocalChat, parse_json
from flicks.assistant.narrator import Narrator, facts
from flicks.core import Recommender, Session, load_catalog
from flicks.search import TitleIndex
from flicks.systemone import PrivacyError
from helpers import CATALOG, FakeChat, app_client

CATALOGUE = load_catalog(CATALOG)


def call(tool, **args):
    return json.dumps({'tool': tool, 'args': args})


class LocalChatTests(unittest.TestCase):
    def test_only_a_model_on_this_machine_is_accepted(self):
        for url in ('http://192.168.1.5:11434', 'https://api.example.com', 'http://example.com'):
            with self.subTest(url), self.assertRaises(PrivacyError):
                LocalChat(url, 'm')
        for url in ('', 'ftp://127.0.0.1', 'not a url'):
            with self.subTest(url), self.assertRaises(ValueError):
                LocalChat(url, 'm')
        chat = LocalChat('http://127.0.0.1:11434/v1/', 'qwen3.5:2b')
        self.assertEqual(chat.url, 'http://127.0.0.1:11434/v1/chat/completions')
        self.assertTrue(LocalChat('http://localhost:8080', 'm').url.startswith('http://localhost:8080/v1/'))

    def test_an_absent_server_is_an_llm_error_not_a_crash(self):
        chat = LocalChat('http://127.0.0.1:9', 'm', timeout=1)  # the discard port: nothing listens
        with self.assertRaises(LLMError):
            chat.complete([{'role': 'user', 'content': 'hi'}])
        self.assertFalse(chat.status()['available'])

    def test_a_busy_model_is_an_llm_error_after_the_wait(self):
        chat = LocalChat('http://127.0.0.1:9', 'm', timeout=1)
        chat.lock.acquire()  # another generation is running
        try:
            with self.assertRaisesRegex(LLMError, 'busy'):
                chat.complete([{'role': 'user', 'content': 'hi'}], wait=0.05)
        finally:
            chat.lock.release()

    def test_parse_json_finds_the_object_in_a_chatty_reply(self):
        self.assertEqual(parse_json('Sure! ```json\n{"tool": "give_up", "args": {}}\n```'), {'tool': 'give_up', 'args': {}})
        for bad in ('no json here', '{"unterminated": ', '[1, 2]'):
            with self.subTest(bad), self.assertRaises(LLMError):
                parse_json(bad)


class NarratorTests(unittest.TestCase):
    def setUp(self):
        self.engine = Recommender(CATALOGUE)
        self.session = Session(mood='curious')
        self.pick = self.engine.explain_item({'m001': 1}, self.session, 'm004')  # Moon, after liking Arrival

    def test_facts_hold_only_the_pick_and_the_scene(self):
        given = facts(self.pick, self.session)
        self.assertEqual(given['title'], 'Moon')
        self.assertEqual(given['your scene']['mood'], 'curious')
        self.assertTrue(given['about'].endswith('.') and len(given['about']) <= 221)
        self.assertNotIn('score', json.dumps(given))
        self.assertIn('matches your ratings', given['main reasons'])
        popular = facts({**self.pick, 'popular': True}, self.session)
        self.assertNotIn('matches your ratings', popular['main reasons'])  # the prior, not the user, supplied taste

    def test_a_grounded_reply_is_returned_and_cached(self):
        chat = FakeChat('Moon is a quiet, curious science-fiction mystery, which suits the mood you asked for.')
        narrator = Narrator(chat, CATALOGUE)
        first = narrator.narrate(1, self.pick, self.session)
        self.assertIn('Moon', first['text'])
        self.assertEqual(narrator.narrate(1, self.pick, self.session), first)
        self.assertEqual(len(chat.requests), 1)  # the second call came from the cache
        self.assertIn('Facts:', chat.requests[0]['messages'][1]['content'])
        self.assertEqual(chat.requests[0]['wait'], 2)  # never queues behind a long generation

    def test_replies_that_stray_from_the_facts_are_rejected(self):
        for reply in ('Like Interstellar, Moon explores isolation in space.',             # a title it was not given
                      'You will love it. As “The Martian” showed, you enjoy this.',     # quoted title
                      'Moon is 87% likely to please you.',                                # numbers it should not state
                      'See https://example.com for more.',
                      'ok',
                      'x' * 400):
            with self.subTest(reply), self.assertRaises(LLMError):
                Narrator(FakeChat(reply), CATALOGUE).narrate(1, self.pick, self.session)

    def test_titles_inside_the_given_title_and_common_words_are_not_flagged(self):
        narrator = Narrator(FakeChat(), CATALOGUE)
        self.assertEqual(narrator.named_titles('Moon fits your curious mood tonight.'), set())  # first word of a sentence
        self.assertEqual(narrator.named_titles('Tonight, try Moon.'), {'moon'})
        self.assertEqual(narrator.named_titles('A slow film under the moon, with contact between people.'), set())


class AgentTests(unittest.TestCase):
    def agent(self, *replies, error=None):
        titles = TitleIndex(CATALOGUE)
        self.chat = FakeChat(*replies, error=error)
        return AgentInterpreter(CommandInterpreter(CATALOGUE, titles), self.chat, CATALOGUE, titles)

    def test_rules_win_and_the_model_is_not_asked(self):
        agent = self.agent()
        for text in ('Like Arrival', 'relaxing, 90 minutes', 'play Moon', 'not relaxing'):
            with self.subTest(text):
                self.assertNotEqual(agent.parse(text).get('parser'), 'llm')
        self.assertEqual(self.chat.requests, [])

    def test_looks_up_a_title_then_shows_titles_like_it(self):
        agent = self.agent(call('lookup_title', title='Arrival'), call('finish_similar', id='m001', reply='Here are films like Arrival.'))
        result = agent.parse('something like that alien language movie arrival but not long')
        self.assertEqual((result['intent'], result['similar'], result['parser']), ('search', 'm001', 'llm'))
        self.assertEqual(result['steps'], ['Looked up “Arrival”: 1 found'])
        self.assertIn('Tool result', self.chat.requests[1]['messages'][-1]['content'])
        self.assertTrue(all(r['json_mode'] for r in self.chat.requests))

    def test_a_scene_is_validated_like_manual_controls(self):
        agent = self.agent(call('finish_scene', mood='relaxing', max_minutes=95, avoid_genres=['Horror'], reply='Calm and short.'))
        result = agent.parse('i had a long week and just want to switch off, nothing scary')
        self.assertEqual(result['intent'], 'session')
        self.assertEqual(result['patch'], {'mood': 'relaxing', 'minutes': 95, 'excluded_genres': ['horror']})
        self.assertEqual(result['summary'], 'Set mood: relaxing; time limit 95 minutes; avoid horror.')

    def test_invalid_proposals_are_sent_back_and_unknown_ids_refused(self):
        agent = self.agent(call('finish_scene', mood='spooky'),                 # not a mood
                           call('finish_similar', id='m999'),                    # never looked up
                           call('finish_scene', intensity=2),                    # out of range
                           call('finish_scene', intensity=0.9, reply='Intense.'))
        result = agent.parse('give me an adrenaline rush tonight')
        self.assertEqual(result['patch'], {'intensity': 0.9})
        errors = [r['messages'][-1]['content'] for r in self.chat.requests[1:]]
        self.assertTrue(all(e.startswith('Tool result: "error:') for e in errors), errors)

    def test_preview_and_apply_get_the_same_answer(self):
        agent = self.agent(call('finish_search', query='space', reply='Space films.'))
        first = agent.parse('i fancy going to space tonight with something')
        self.assertEqual(agent.parse('I fancy going to space tonight with something!'), first)
        self.assertEqual(len(self.chat.requests), 1)

    def test_an_unavailable_or_unhelpful_model_falls_back_to_the_rules(self):
        offline = self.agent(error=LLMError('The local model is unreachable')).parse('qwertyuiop asdf')
        self.assertEqual((offline['intent'], offline['parser']), ('unknown', 'rules'))
        self.assertIn('could not help (The local model is unreachable)', offline['note'])
        gave_up = self.agent(call('give_up', reply='I only help choose films.')).parse('what is the weather')
        self.assertEqual(gave_up['intent'], 'unknown')
        self.assertIn('(I only help choose films.)', gave_up['note'])
        endless = self.agent(*[call('lookup_title', title='x')] * 5).parse('qwertyuiop asdf')
        self.assertIn('did not finish', endless['note'])
        self.assertEqual(len(self.chat.requests), 4)

    def test_the_agent_cannot_rate_or_play_unlooked_titles(self):
        agent = self.agent(call('rate', id='m001', value=1), call('finish_play', id='m001'), call('give_up'))
        self.assertEqual(agent.parse('qwertyuiop asdf')['intent'], 'unknown')
        self.assertIn("unknown tool 'rate'", self.chat.requests[1]['messages'][-1]['content'])


class LlmApiTests(unittest.TestCase):
    def test_explain_returns_a_narration_or_null(self):
        with tempfile.TemporaryDirectory() as temp:
            with app_client(Path(temp)) as (client, _):
                self.assertFalse(client.get('/api/state').json()['llm']['available'])
                none = client.post('/api/explain', json={'id': 'm004'}).json()
                self.assertIsNone(none['narration'])
            chat = FakeChat('Moon suits your curious mood and the science fiction you like.', 'You may prefer Interstellar instead.')
            with app_client(Path(temp)/'b', chat=chat) as (client, _):
                self.assertTrue(client.get('/api/state').json()['llm']['available'])
                client.post('/api/feedback', json={'id': 'm001', 'value': 1})
                body = {'id': 'm004', 'session': {'mood': 'curious'}}
                self.assertIn('curious mood', client.post('/api/explain', json=body).json()['narration'])
                stray = client.post('/api/explain', json={'id': 'm002'}).json()
                self.assertIsNone(stray['narration'])
                self.assertIn('Interstellar', stray['note'])
                self.assertEqual(client.post('/api/explain', json={'id': 'nope'}).status_code, 404)

    def test_command_preview_and_apply_through_the_agent(self):
        chat = FakeChat(call('finish_scene', mood='uplifting', max_minutes=100, reply='Something cheerful and short.'))
        # Without the Ask student, so the request reaches the language model tier.
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat, ask_student=None) as (client, _):
            text = {'text': 'cheer me up after a rough day, nothing too long'}
            preview = client.post('/api/command/preview', json=text).json()
            self.assertEqual(preview['command']['parser'], 'llm')
            applied = client.post('/api/command/apply', json=text).json()
            self.assertEqual((applied['session']['mood'], applied['session']['minutes']), ('uplifting', 100))
            self.assertEqual(len(chat.requests), 1)
            self.assertIn('fake LLM', client.get('/api/state').json()['assistant'])


if __name__ == '__main__':
    unittest.main()
