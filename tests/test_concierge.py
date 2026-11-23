import json
from pathlib import Path
import tempfile
import unittest

from flicks.collaborative import ItemNeighbours
from helpers import FakeChat, app_client


def ask(client, *texts, shown=(), session=None):
    messages = [{'role': 'user', 'text': text} for text in texts]
    reply = client.post('/api/concierge', json={'messages': messages, 'shown': list(shown), **({'session': session} if session else {})})
    return reply, [json.loads(line) for line in reply.text.splitlines()] if reply.status_code == 200 else []


class PitchChat(FakeChat):
    """Words the pitch from the facts it is sent: the first two picks, then `extra(picks)` (another title)."""
    def __init__(self, extra):
        super().__init__()
        self.make_extra, self.extra = extra, None

    def complete(self, messages, **options):
        self.requests.append({'messages': list(messages)})
        picks = json.loads(messages[1]['content'].removeprefix('Facts:\n'))['picks']
        self.extra = self.make_extra(picks)
        return f"{picks[0]['title']} and {picks[1]['title']} suit tonight, much like \"{self.extra}\"."


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
        chat = FakeChat('How long have you got tonight?', 'Try Blade Runner instead.')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            _, events = ask(client, 'something tense')
            self.assertEqual(events[-1], {'done': True, 'step': 'time', 'text': 'How long have you got tonight?', 'model': True})
            self.assertIn('"they said": "something tense"', chat.requests[0]['messages'][1]['content'])
            _, events = ask(client, 'something tense', 'about 90 minutes')
            names = [p['content']['title'] for p in next(e for e in events if 'picks' in e)['picks']]
            self.assertFalse(events[-1]['model'])
            self.assertIn(names[0], events[-1]['text'])

    def test_a_pitch_may_name_a_title_the_viewer_liked(self):
        chat = PitchChat(lambda picks: next(t for p in picks for t in p['because you liked']))
        with tempfile.TemporaryDirectory() as temp:
            # Viewers who liked Arrival also liked these, so a pick can say "because you liked Arrival".
            neighbours = Path(temp)/'n.json'
            near = [[content_id, 0.9] for content_id in ('m002', 'm003', 'm004', 'm006', 'm007', 'm016')]
            neighbours.write_text(json.dumps({'format': ItemNeighbours.FORMAT, 'neighbours': {'m001': near}}))
            with app_client(Path(temp), chat=chat, neighbours=neighbours) as (client, _):
                client.post('/api/feedback', json={'id': 'm001', 'value': 1})
                _, events = ask(client, 'a science fiction film for 2 hours')
            self.assertEqual(chat.extra, 'Arrival')
            self.assertTrue(events[-1]['model'], events[-1]['text'])
            self.assertIn('Arrival', events[-1]['text'])

    def test_a_pitch_may_name_the_title_the_viewer_asked_about(self):
        chat = PitchChat(lambda picks: 'The Martian')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            for text in ('something like The Martian for 2 hours', 'something like the martian for 2 hours'):
                with self.subTest(text=text):
                    _, events = ask(client, text)
                    self.assertTrue(events[-1]['model'], events[-1]['text'])
                    self.assertIn('The Martian', events[-1]['text'])

    def test_rejects_an_empty_conversation(self):
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp)) as (client, _):
            reply, _ = ask(client, '   ')
            self.assertEqual(reply.status_code, 400)
            self.assertEqual(client.post('/api/concierge', json={'messages': []}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
