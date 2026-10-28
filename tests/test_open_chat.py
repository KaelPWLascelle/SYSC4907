import json
from pathlib import Path
import tempfile
import unittest

from helpers import FakeChat, app_client


def ask(client, *texts, shown=(), previous=()):
    messages = [{'role': 'user' if n % 2 == 0 else 'assistant', 'text': text} for n, text in enumerate(texts)]
    reply = client.post('/api/concierge', json={'messages': messages, 'shown': list(shown), 'previous': list(previous)})
    assert reply.status_code == 200, reply.text
    return [json.loads(line) for line in reply.text.splitlines()]


def plan(**fields):
    return json.dumps(fields)


def titles(events):
    return [p['content']['title'] for e in events if 'picks' in e for p in e['picks']]


def said(events):
    return ''.join(e.get('delta', '') for e in events)


class OpenChatTests(unittest.TestCase):
    def test_a_search_shows_the_titles_found_and_an_answer_from_them(self):
        chat = FakeChat(plan(action='find', query='Paris'), 'Amélie is set in Paris. The Red Balloon too.')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            events = ask(client, 'films set in Paris')
            self.assertEqual(events[0]['understood'], ['“Paris”'])
            self.assertEqual(set(titles(events)), {'Amélie', 'The Red Balloon'})
            self.assertEqual(events[-1], {'done': True, 'step': 'picks', 'text': said(events), 'model': True})
            self.assertEqual(said(events), 'Amélie is set in Paris. The Red Balloon too.')
            # The planner was held to a schema; the answer saw the results, including why each matched.
            self.assertEqual(chat.requests[0]['schema']['properties']['action']['enum'],
                             ['find', 'similar', 'about', 'previous', 'help'])
            self.assertIn('"title": "Amélie"', chat.requests[1]['messages'][1]['content'])

    def test_a_sentence_naming_a_title_outside_the_results_is_never_shown(self):
        chat = FakeChat(plan(action='find', query='Paris'),
                        'You could try Amélie. Blade Runner is better though. The Red Balloon is short.')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            events = ask(client, 'films set in Paris')
            self.assertEqual(said(events), 'You could try Amélie. The Red Balloon is short.')
            self.assertEqual(events[-1]['text'], said(events))  # the streamed text is the final text

    def test_a_cut_off_answer_keeps_its_whole_sentences_and_markdown_is_dropped(self):
        chat = FakeChat(plan(action='similar', title='Arrival'), '**Contact** fits a thoughtful night. Moon is a slow')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            events = ask(client, 'something like Arrival')
            self.assertEqual(said(events), 'Contact fits a thoughtful night.')
            self.assertNotIn('Arrival', titles(events))
            self.assertIn('Like Arrival', events[0]['understood'])

    def test_a_list_squeezed_into_a_line_reads_as_sentences_and_quotes_stay_closed(self):
        chat = FakeChat(plan(action='find', query='Paris'), 'Two picks: 1. "Amélie." 2. The Red Balloon is short.')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            self.assertEqual(said(ask(client, 'films set in Paris')), 'Two picks: "Amélie." The Red Balloon is short.')

    def test_flicks_own_readers_overrule_the_plan_for_lengths_and_things_to_avoid(self):
        # The model invents a year range and misses "no horror"; Flicks reads the length and the avoid itself.
        chat = FakeChat(plan(action='find', mood='tense', decade=2000, max_minutes=180), 'Here are tense picks.')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            events = ask(client, 'something tense, no horror, an hour and a half')
            self.assertEqual(events[0]['patch']['minutes'], 90)
            self.assertEqual(events[0]['patch']['excluded_genres'], ['horror'])
            picks = next(e for e in events if 'picks' in e)
            self.assertEqual(picks['session']['minutes'], 90)  # a scene the viewer can use on Home
            for pick in picks['picks']:
                self.assertNotIn('horror', pick['content']['genres'])
                self.assertLessEqual(pick['content']['minutes'], 90)
            self.assertNotIn('years', json.dumps(events[0]))

    def test_follow_ups_see_the_last_titles_in_full(self):
        chat = FakeChat(plan(action='previous'), 'The Red Balloon is the shortest, at 34 minutes.')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            events = ask(client, 'films set in Paris', 'Amélie and The Red Balloon.', 'which is shortest?',
                         previous=['m020', 'm035'])
            self.assertEqual(titles(events), ['Amélie', 'The Red Balloon'])
            self.assertIn('Viewer: films set in Paris\nFlicks: Amélie and The Red Balloon.\nViewer: which is shortest?',
                          chat.requests[0]['messages'][1]['content'])
            self.assertIn('"minutes": 34', chat.requests[1]['messages'][1]['content'])

    def test_a_question_about_flicks_gets_the_help_line_without_a_second_call(self):
        chat = FakeChat(plan(action='help'))
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            events = ask(client, 'what can you do?')
            self.assertEqual(events[-1]['step'], 'help')
            self.assertIn('Tom Hanks films', events[-1]['text'])
            self.assertEqual(len(chat.requests), 1)

    def test_an_unknown_title_says_so_and_shows_no_cards(self):
        chat = FakeChat(plan(action='about', title='Iron Man'), 'Flicks does not have that one.')
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            events = ask(client, 'who is in Iron Man?')
            self.assertEqual(titles(events), [])
            self.assertEqual(events[-1]['step'], 'answer')
            self.assertIn('not in the catalogue', chat.requests[1]['messages'][1]['content'])

    def test_a_busy_or_failing_model_falls_back_to_the_questions(self):
        from flicks.assistant.llm import LLMError
        chat = FakeChat(error=LLMError('busy'))
        with tempfile.TemporaryDirectory() as temp, app_client(Path(temp), chat=chat) as (client, _):
            events = ask(client, 'something tense')
            self.assertEqual(events[-1]['step'], 'time')
            self.assertFalse(events[-1]['model'])


if __name__ == '__main__':
    unittest.main()
