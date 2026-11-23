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
                self.assertIn('hidden', done['note'])

    def test_a_one_word_title_counts_only_when_quoted(self):
        # "Alien" is also a word and a name; unquoted, it is not read as the film.
        talker = TitleChat(FakeChat(), CATALOGUE)
        self.assertEqual(talker.check('An Alien crew member is never seen.', self.given), 'An Alien crew member is never seen.')
        with self.assertRaises(LLMError):
            talker.check('Fans also like "Alien".', self.given)

    def test_an_answer_calling_it_fine_for_kids_without_a_rating_is_replaced(self):
        # Small models say "suitable for all ages" with no rating to go on (Granite 4.0 1B did, for The Godfather).
        talker = TitleChat(FakeChat(), CATALOGUE)
        for reply in ('Moon is not scary, and its content is suitable for all ages.',
                      'It is a gentle film and is kid-friendly.',
                      'Moon is fine for kids.',
                      'It is not rated as scary or inappropriate for children.',
                      'It is suitable for older kids and adults.',
                      'Its intensity suggests it is suitable for a wide audience, including children.'):
            with self.subTest(reply=reply):
                answer = talker.check(reply, self.given, 'Is it OK for kids?')
                self.assertNotEqual(answer, reply)
                self.assertIn('age rating', answer)
                self.assertNotRegex(answer.lower(), r'\bsuitable\b|\bfine\b|friendly')

    def test_an_answer_that_hedges_about_kids_is_kept(self):
        talker = TitleChat(FakeChat(), CATALOGUE)
        for reply in ('The age rating is not specified, so it is unclear if it is suitable for your kids.',
                      'It contains violence, so it may not be suitable for young children.',
                      'Flicks doesn’t know if it is OK for kids.',
                      'It is suitable for a relaxing evening.',
                      'Is it OK for your kids? Flicks has no age rating for it.'):
            with self.subTest(reply=reply):
                self.assertEqual(talker.check(reply, self.given, 'Is it OK for kids?'), reply)

    def test_the_kids_check_only_reads_answers_about_kids(self):
        # A plot answer that calls an animated film "family-friendly" is about its tone, not a rating.
        reply = 'Moon is a family-friendly story about a rat who cooks.'
        self.assertEqual(TitleChat(FakeChat(), CATALOGUE).check(reply, self.given, 'What is it about?'), reply)

    def test_the_kids_sentence_warns_about_intense_titles(self):
        given = dict(self.given, intensity='intense', genres=['horror', 'thriller'])
        answer = TitleChat(FakeChat(), CATALOGUE).check('It is suitable for kids.', given, 'OK for kids?')
        self.assertIn('intense', answer)
        self.assertIn('horror', answer)

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

    def test_a_closing_think_tag_with_no_opening_ends_the_answer(self):
        # Templates that open the thinking block themselves (LFM3) can leave "</think>" and a second answer.
        with tempfile.NamedTemporaryFile(suffix='.gguf') as model:
            llama = FakeLlama('It runs 81 minutes.</think>It is 81 minutes long.')
            chat = EmbeddedChat(model.name, runtime=lambda: llama, idle_seconds=60)
            self.assertEqual(chat.complete([{'role': 'user', 'content': 'How long?'}]), 'It runs 81 minutes.')
            chat._timer.cancel()

    def test_models_broken_on_the_gpu_run_on_the_cpu(self):
        # Granite 4.0 prints only "@@@@" on Metal (docs/llm-benchmark.md), so it never gets GPU layers.
        with tempfile.TemporaryDirectory() as temp:
            for name, layers in (('granite-4.0-1b-Q4_K_M.gguf', 0), ('Qwen3.5-2B-Q4_K_M.gguf', -1)):
                with self.subTest(name=name):
                    path = Path(temp)/name
                    path.write_bytes(b'x')
                    llama = FakeLlama('Hi.')
                    chat = EmbeddedChat(path, runtime=lambda llama=llama: llama, idle_seconds=60)
                    chat.complete([{'role': 'user', 'content': 'Hi'}])
                    self.assertEqual(llama.options['n_gpu_layers'], layers)
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
