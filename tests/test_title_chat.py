import json
from pathlib import Path
import tempfile
import unittest

from flicks.assistant.embedded import EmbeddedChat
from flicks.assistant.llm import LLMError
from flicks.assistant.title_chat import TitleChat, facts
from flicks.core import Recommender, Session, load_catalog
from helpers import CATALOG, FakeChat, app_client

CATALOGUE = load_catalog(CATALOG)


class FakeLlama:
    """Stands in for llama_cpp.Llama: streams `reply` in two-character pieces."""
    loads = 0

    def __init__(self, reply):
        self.reply = reply

    def __call__(self, **options):
        FakeLlama.loads += 1
        self.options = options
        return self

    def create_chat_completion(self, messages, **options):
        self.messages = messages
        for i in range(0, len(self.reply), 2):
            yield {'choices': [{'delta': {'content': self.reply[i:i + 2]}}]}


class TitleChatTests(unittest.TestCase):
    def setUp(self):
        self.session = Session(mood='curious', minutes=100)
        self.pick = Recommender(CATALOGUE).explain_item({'m001': 1}, self.session, 'm004')  # Moon, after Arrival
        self.given = facts(self.pick['content'], self.pick, self.session)

    def test_facts_hold_the_title_its_reasons_and_the_evening(self):
        self.assertEqual(self.given['title'], 'Moon')
        self.assertEqual(self.given['kind'], 'film')
        self.assertIn('description', self.given)
        self.assertEqual(self.given['your evening'], {'mood': 'curious', 'minutes available': 100, 'fits the time you have': True})
        self.assertIn('main reasons', self.given['why Flicks picked it'])
        self.assertNotIn('score', json.dumps(self.given))

    def test_an_answer_streams_then_is_checked(self):
        chat = FakeChat('Moon is a quiet mystery about a lunar worker.')
        events = list(TitleChat(chat, CATALOGUE).stream(self.given, 'What is it about?'))
        self.assertEqual(events[-1], {'done': True, 'ok': True, 'answer': 'Moon is a quiet mystery about a lunar worker.'})
        system, question = chat.requests[0]['messages'][0], chat.requests[0]['messages'][-1]
        self.assertIn('"title": "Moon"', system['content'])
        self.assertEqual(question, {'role': 'user', 'content': 'What is it about?'})

    def test_an_answer_naming_a_title_it_was_not_given_is_withdrawn(self):
        for reply in ('If you like Moon, try Blade Runner next.', 'See www.example.com for more.'):
            with self.subTest(reply=reply):
                done = list(TitleChat(FakeChat(reply), CATALOGUE).stream(self.given, 'Anything similar?'))[-1]
                self.assertFalse(done['ok'])
                self.assertIn('withdrawn', done['note'])

    def test_follow_ups_keep_the_last_turns_only(self):
        chat = FakeChat('Sam Rockwell stars.')
        history = [{'question': f'q{i}', 'answer': f'a{i}'} for i in range(5)]
        list(TitleChat(chat, CATALOGUE).stream(self.given, 'Who else?', history))
        messages = chat.requests[0]['messages']
        self.assertEqual([m['content'] for m in messages[1:-1]], ['q2', 'a2', 'q3', 'a3', 'q4', 'a4'])
        with self.assertRaises(ValueError):
            list(TitleChat(chat, CATALOGUE).stream(self.given, '   '))


class EmbeddedChatTests(unittest.TestCase):
    def test_loads_once_on_first_use_and_drops_thinking(self):
        with tempfile.NamedTemporaryFile(suffix='.gguf') as model:
            llama = FakeLlama('<think>hmm</think>Moon stars Sam Rockwell.')
            FakeLlama.loads = 0
            chat = EmbeddedChat(model.name, runtime=lambda: llama, idle_seconds=60)
            self.assertEqual(chat.status()['message'], 'Loads on first question')
            self.assertEqual(chat.complete([{'role': 'user', 'content': 'Who is in it?'}]), 'Moon stars Sam Rockwell.')
            chat.complete([{'role': 'user', 'content': 'Again?'}])
            self.assertEqual(FakeLlama.loads, 1)
            self.assertEqual(chat.status()['message'], 'Loaded')
            chat._timer.cancel()

    def test_reports_what_is_missing(self):
        self.assertIn('llama-cpp-python', EmbeddedChat('x.gguf', runtime=lambda: None).status()['message'])
        missing = EmbeddedChat('/nowhere/x.gguf', runtime=lambda: FakeLlama(''))
        self.assertFalse(missing.status()['available'])
        with self.assertRaises(LLMError):
            missing.complete([{'role': 'user', 'content': 'hi'}])


class AskTitleApiTests(unittest.TestCase):
    def test_streams_newline_delimited_json(self):
        with tempfile.TemporaryDirectory() as temp:
            with app_client(Path(temp)) as (client, _):
                self.assertEqual(client.post('/api/ask-title', json={'id': 'm004', 'question': 'Who?'}).status_code, 409)
            chat = FakeChat('Moon is about a lunar worker.')
            with app_client(Path(temp)/'b', chat=chat) as (client, _):
                reply = client.post('/api/ask-title', json={'id': 'm004', 'question': 'What is it about?'})
                self.assertEqual(reply.headers['content-type'], 'application/x-ndjson')
                events = [json.loads(line) for line in reply.text.splitlines()]
                self.assertEqual(''.join(e.get('delta', '') for e in events), 'Moon is about a lunar worker.')
                self.assertTrue(events[-1]['ok'])
                self.assertEqual(client.post('/api/ask-title', json={'id': 'nope', 'question': 'x'}).status_code, 404)
                self.assertEqual(client.post('/api/ask-title', json={'id': 'm004', 'question': ''}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
