import json
from pathlib import Path
import tempfile
import unittest

from helpers import FakeChat, app_client


def ask(client, *texts, shown=(), session=None):
    messages = [{'role': 'user', 'text': text} for text in texts]
    reply = client.post('/api/concierge', json={'messages': messages, 'shown': list(shown), **({'session': session} if session else {})})
    return reply, [json.loads(line) for line in reply.text.splitlines()] if reply.status_code == 200 else []


class ConciergeTests(unittest.TestCase):
    def test_asks_for_a_mood_then_the_time_then_offers_three_picks(self):
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp)) as (client, _):
            _, events = ask(client, 'hi')
            self.assertEqual(events[-1]['step'], 'mood')
            _, events = ask(client, 'something tense')
            self.assertIn('Tense', events[0]['understood'])
            self.assertEqual(events[-1]['step'], 'time')
            _, events = ask(client, 'something tense', 'about 90 minutes')
            self.assertEqual(events[0]['understood'], ['Tense', 'Up to 90 min'])
            picks = next(e for e in events if 'picks' in e)
            self.assertEqual(len(picks['picks']), 3)
            self.assertTrue(all(p['content']['minutes'] <= 90 for p in picks['picks']))
            self.assertEqual(picks['session']['minutes'], 90)
            done = events[-1]
            self.assertEqual(done['step'], 'picks')
            self.assertFalse(done['model'])  # no language model: Flicks' own sentence
            self.assertIn(picks['picks'][0]['content']['title'], done['text'])

    def test_one_full_answer_or_surprise_me_skips_the_questions(self):
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp)) as (client, _):
            for text in ('a comedy for 2 hours', 'surprise me'):
                with self.subTest(text=text):
                    _, events = ask(client, text)
                    self.assertEqual(events[-1]['step'], 'picks')

    def test_shown_titles_are_not_offered_again_and_genres_filter(self):
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp)) as (client, _):
            _, events = ask(client, 'a comedy for 2 hours')
            first = [p['content'] for p in next(e for e in events if 'picks' in e)['picks']]
            self.assertTrue(all('comedy' in item['genres'] for item in first))
            _, events = ask(client, 'a comedy for 2 hours', shown=[item['id'] for item in first])
            again = {p['content']['id'] for p in next(e for e in events if 'picks' in e)['picks']}
            self.assertFalse(again & {item['id'] for item in first})

    def test_the_model_words_the_reply_and_a_stray_title_falls_back(self):
        # Without a plan from the model, the questions; the model still words them.
        chat = FakeChat('no plan', 'How long have you got tonight?', 'no plan', 'Try Blade Runner instead.')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            _, events = ask(client, 'something tense')
            self.assertEqual(events[-1], {'done': True, 'step': 'time', 'text': 'How long have you got tonight?', 'model': True})
            self.assertIn('"they said": "something tense"', chat.requests[1]['messages'][1]['content'])
            _, events = ask(client, 'something tense', 'about 90 minutes')
            names = [p['content']['title'] for p in next(e for e in events if 'picks' in e)['picks']]
            self.assertFalse(events[-1]['model'])
            self.assertIn(names[0], events[-1]['text'])

    def test_a_reply_cut_off_by_the_token_limit_ends_at_its_last_whole_sentence(self):
        chat = FakeChat('no plan', 'Got it, something tense? How much time do you',
                        'no plan', 'All three suit a tense night. The first is a slow burn that',
                        'no plan', 'These three are all')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            _, events = ask(client, 'something tense')
            self.assertEqual(events[-1], {'done': True, 'step': 'time', 'text': 'Got it, something tense?', 'model': True})
            _, events = ask(client, 'something tense', 'about 90 minutes')
            self.assertEqual(events[-1]['text'], 'All three suit a tense night.')
            self.assertTrue(events[-1]['model'])
            # No sentence finished: Flicks' own sentence instead.
            _, events = ask(client, 'something tense', 'about 90 minutes')
            names = [p['content']['title'] for p in next(e for e in events if 'picks' in e)['picks']]
            self.assertFalse(events[-1]['model'])
            self.assertIn(names[0], events[-1]['text'])

    def test_rejects_an_empty_conversation(self):
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp)) as (client, _):
            reply, _ = ask(client, '   ')
            self.assertEqual(reply.status_code, 400)
            self.assertEqual(client.post('/api/concierge', json={'messages': []}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
