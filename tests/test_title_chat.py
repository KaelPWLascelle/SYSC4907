import json
from pathlib import Path
import tempfile
import unittest

from flicks.assistant.embedded import EmbeddedChat
from flicks.assistant.llm import LLMError
from flicks.assistant.title_chat import TitleChat, directors, facts
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
        self.messages, self.sampling = messages, options
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
        self.assertEqual(self.given['your evening'], {'mood': 'curious', 'minutes available': 100,
                                                      'fits the time you have': True, 'matches the mood you asked for': True})
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

    def test_the_kids_sentence_says_whether_it_may_be_scary(self):
        from flicks.assistant.title_chat import kids_sentence
        base = {'kind': 'film', 'age rating': 'not known to Flicks'}
        cases = (({'intensity': 'gentle', 'genres': ['animation', 'family'], 'moods': ['uplifting']},
                  ['unlikely to be scary', 'family film']),
                 ({'intensity': 'balanced', 'genres': ['crime', 'drama'], 'moods': ['reflective']},
                  ['may be scary or too much for young viewers', 'crime']),
                 ({'intensity': 'balanced', 'genres': ['drama'], 'moods': ['tense']},
                  ['may be scary or too much for young viewers', 'tense']),
                 ({'intensity': 'intense', 'genres': ['action'], 'moods': []},
                  ['an intense film', 'may be scary']),
                 # Balanced and not a family title: the catalogue can't say (Game of Thrones is "balanced" too).
                 ({'intensity': 'balanced', 'genres': ['drama', 'fantasy'], 'moods': ['reflective']},
                  ['balanced in intensity', 'preview it before showing it to young children']))
        for facts_, words in cases:
            with self.subTest(facts=facts_):
                sentence = kids_sentence({**base, **facts_})
                self.assertTrue(sentence.startswith('Flicks doesn’t know its age rating'))
                for word in words:
                    self.assertIn(word, sentence)

    def test_facts_say_when_the_mood_does_not_match(self):
        given = facts(self.pick['content'], self.pick, Session(mood='relaxing', minutes=100))
        self.assertFalse(given['your evening']['matches the mood you asked for'])  # Moon is reflective and curious
        given = facts(self.pick['content'], self.pick, Session(mood='any', minutes=100))
        self.assertTrue(given['your evening']['matches the mood you asked for'])

    def test_directors_are_read_from_the_description(self):
        cases = {
            'Toy Story is a 1995 film directed by John Lasseter, and written by Joss Whedon.': ['John Lasseter'],
            'It was directed by Roger Allers and Rob Minkoff and written by Irene Mecchi.': ['Roger Allers', 'Rob Minkoff'],
            'A 1987 comedy directed by James L. Brooks. The film stars Holly Hunter.': ['James L. Brooks'],
            'Directed by the Wachowskis.': [],
            'A linguist meets visitors.': [],
        }
        for description, names in cases.items():
            with self.subTest(description=description):
                self.assertEqual(directors(description), names)

    def test_facts_name_the_director_when_the_description_does(self):
        item = dict(self.pick['content'], description='Moon is a 2009 film directed by Duncan Jones.')
        self.assertEqual(facts(item)['directed by'], ['Duncan Jones'])
        self.assertNotIn('directed by', self.given)

    def test_an_answer_that_misses_the_director_gets_flicks_own(self):
        given = dict(self.given, **{'directed by': ['Duncan Jones']})
        talker = TitleChat(FakeChat(), CATALOGUE)
        self.assertEqual(talker.check('Flicks only has details about this one.', given, 'Who directed it?'),
                         'It was directed by Duncan Jones.')
        self.assertEqual(talker.check('Duncan Jones directed it.', given, 'Who directed it?'), 'Duncan Jones directed it.')
        self.assertEqual(talker.check('It is a quiet mystery.', given, 'What is it about?'), 'It is a quiet mystery.')

    def test_an_answer_that_contradicts_tonight_gets_flicks_own(self):
        talker = TitleChat(FakeChat(), CATALOGUE)
        evening = {'mood': 'relaxing', 'minutes available': 100}
        too_long = dict(self.given, minutes=153, **{'your evening': {**evening, 'fits the time you have': False,
                                                                     'matches the mood you asked for': True}})
        answer = talker.check('Yes, it fits your evening perfectly.', too_long, 'Does it fit tonight?')
        self.assertIn('153 minutes', answer)
        self.assertIn('100', answer)
        self.assertNotRegex(answer, r'^Yes')
        wrong_mood = dict(self.given, moods=['tense'], **{'your evening': {**evening, 'fits the time you have': True,
                                                                           'matches the mood you asked for': False}})
        answer = talker.check('Yes, it fits perfectly for a relaxing evening.', wrong_mood, 'Does it fit tonight?')
        self.assertIn('tense', answer)
        self.assertIn('relaxing', answer)
        fits = dict(self.given, **{'your evening': {**evening, 'fits the time you have': True,
                                                    'matches the mood you asked for': True}})
        answer = talker.check('It does not fit your evening.', fits, 'Does it fit tonight?')
        self.assertIn('fits', answer)
        # When tonight doesn't fit, Flicks' sentence is shown even if the model said so too: it names both reasons.
        for reply, given in (('It runs over your 100 minutes, so it does not fit.', too_long),
                             ('It is 153 minutes long and doesn’t fit the time you have.', too_long),
                             ('It fits the time, but it is tense rather than relaxing.', wrong_mood)):
            with self.subTest(reply=reply):
                self.assertIn('may not suit tonight', talker.check(reply, given, 'Is it right for tonight?'))
        self.assertEqual(talker.check('Yes, it fits nicely.', fits, 'Is it right for tonight?'), 'Yes, it fits nicely.')

    def test_why_and_fit_questions_are_answered_by_flicks_without_the_model(self):
        chat = FakeChat('The model should not be asked.')
        for question, words in (('Why did Flicks pick this for me?', 'Flicks picked it because'),
                                ('Does it fit tonight?', '97 minutes'),
                                ('Is it scary? Is it OK for my kids?', 'age rating')):
            with self.subTest(question=question):
                done = list(TitleChat(chat, CATALOGUE).stream(self.given, question))[-1]
                self.assertTrue(done['ok'])
                self.assertIn(words, done['answer'])
        self.assertEqual(chat.requests, [])

    def test_the_why_sentence_uses_the_reasons_and_only_real_themes(self):
        from flicks.assistant.title_chat import why_sentence
        given = dict(self.given, genres=['science-fiction', 'drama'], tags=['space'],
                     **{'why Flicks picked it': {'because you liked': ['Arrival'],
                                                 'themes shared with what you liked': ['white', 'science-fiction', 'space'],
                                                 'main reasons': ['matches your ratings', 'fits the mood you asked for']}})
        sentence = why_sentence(given)
        self.assertIn('Arrival', sentence)
        self.assertIn('fits the mood you asked for', sentence)
        self.assertNotIn('white', sentence)  # a raw term that is not one of the title's genres or tags
        given['why Flicks picked it']['because you liked'] = []
        self.assertIn('science fiction and space', why_sentence(given))
        given['why Flicks picked it']['themes shared with what you liked'] = ['white']
        self.assertEqual(why_sentence(given),
                         'Flicks picked it because it matches your ratings and fits the mood you asked for.')

    def test_when_tonight_does_not_fit_flicks_says_so_whatever_the_model_said(self):
        given = dict(self.given, minutes=153, **{'your evening': {'mood': 'relaxing', 'minutes available': 100,
                                                                  'fits the time you have': False,
                                                                  'matches the mood you asked for': False}})
        answer = TitleChat(FakeChat(), CATALOGUE).check('It may not match your relaxing mood.', given,
                                                        'Is it a good one for tonight?')
        self.assertIn('153 minutes', answer)

    def test_answers_are_cut_to_three_sentences(self):
        reply = 'One. Two. Three. Four.'
        self.assertEqual(TitleChat(FakeChat(), CATALOGUE).check(reply, self.given, 'Tell me more'), 'One. Two. Three.')

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

    def test_answers_are_greedy(self):
        # IBM recommends temperature 0 for Granite 4; the same question always gets the same answer.
        with tempfile.NamedTemporaryFile(suffix='.gguf') as model:
            llama = FakeLlama('Hi.')
            chat = EmbeddedChat(model.name, runtime=lambda: llama, idle_seconds=60)
            chat.complete([{'role': 'user', 'content': 'Hi'}])
            self.assertEqual(llama.sampling['temperature'], 0.0)
            self.assertEqual(llama.sampling.get('repeat_penalty', 1.0), 1.0)
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
