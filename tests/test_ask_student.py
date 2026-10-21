import time
import unittest

from flicks.assistant.ask_student import HEADS, Student, StudentInterpreter
from flicks.assistant.commands import CommandInterpreter
from flicks.core import load_catalog
from flicks.datasets import ask
from flicks.search import TitleIndex
from flicks.text import normalize
from helpers import CATALOG

CATALOGUE = load_catalog(CATALOG)
STUDENT = Student.load()


def interpreter(playable=()):
    titles = TitleIndex(CATALOGUE)
    return StudentInterpreter(CommandInterpreter(CATALOGUE, titles), STUDENT, CATALOGUE, titles, lambda i: i in playable)


class StudentTests(unittest.TestCase):
    def test_reads_described_scenes_and_ignores_everything_else(self):
        cases = {'i need to unwind, nothing scary': {'mood': 'relaxing', 'avoid': 'horror'},
                 'something to listen to on my commute': {'medium': 'listen'},
                 'surprise me with something i have never heard of': {'novelty': 'new'},
                 'set an alarm for seven': {}, 'what should i watch': {}}
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(STUDENT.settings(text), expected)

    def test_probabilities_are_distributions_over_each_heads_options(self):
        for head, probs in STUDENT.probabilities('cheer me up').items():
            self.assertEqual(list(probs), HEADS[head])
            self.assertAlmostEqual(sum(probs.values()), 1)

    def test_it_is_fast_and_small(self):
        start = time.perf_counter()
        for _ in range(200):
            STUDENT.settings('long week, i want to switch off with something gentle, no horror')
        self.assertLess((time.perf_counter() - start) / 200, 0.005)  # well under 5 ms (about 0.2 ms here)

    def test_the_test_set_shares_no_phrase_with_the_training_bank(self):
        phrases = [normalize(p) for v in ask.BANK.values() for p in v] + [normalize(p) for p in ask.GENERIC + ask.OFF_TOPIC]
        for text, _ in ask.TEST:  # DEV shaped the bank, so only TEST measures generalisation
            with self.subTest(text):
                self.assertFalse([p for p in phrases if len(p.split()) >= 2 and p in normalize(text)])
        for text, labels in ask.TEST + ask.DEV:
            with self.subTest(labels=text):
                self.assertTrue(set(labels) <= set(HEADS) and all(v in HEADS[h] for h, v in labels.items()))

    def test_training_is_reproducible_on_a_small_bank(self):
        rows = ask.generate(400, seed=1)
        self.assertEqual(rows, ask.generate(400, seed=1))
        student = ask.train(rows, epochs=8)
        self.assertEqual(student.settings('switch off'), {'mood': 'relaxing'})


class InterpreterTests(unittest.TestCase):
    def test_rules_win(self):
        reader = interpreter()
        self.assertEqual(reader.parse('Like Arrival')['parser'], 'rules')
        self.assertEqual(reader.parse('not relaxing')['intent'], 'unknown')  # a deliberate refusal stands
        self.assertEqual(reader.parse('funny films from the 90s')['intent'], 'search')  # an understood search stands

    def test_fills_in_what_the_rules_could_not_read(self):
        result = interpreter().parse('relaxing, 90 minutes, and nothing scary please')
        self.assertEqual(result['patch'], {'mood': 'relaxing', 'minutes': 90, 'excluded_genres': ['horror']})
        self.assertEqual(result['parser'], 'rules+student')

    def test_reads_a_described_scene(self):
        result = interpreter().parse('i had a rough day, cheer me up')
        self.assertEqual((result['intent'], result['patch'], result['parser']), ('session', {'mood': 'uplifting'}, 'student'))

    def test_a_named_title_after_a_cue_word(self):
        similar = interpreter().parse('something like the martian but lighter')
        self.assertEqual((similar['intent'], similar['similar']), ('search', 'm003'))
        self.assertEqual(interpreter().parse('put on the martian tonight')['id'], 'm003')  # the interface says if it can't play
        # Every cue word is tried, not just the first one ("watch … like X", "like to watch X").
        self.assertEqual(interpreter().parse('watch something like the martian but lighter')['similar'], 'm003')
        self.assertEqual(interpreter().parse('i would like to watch the martian')['intent'], 'play')

    def test_never_drops_a_named_title_or_a_topic(self):
        reader = interpreter()
        missing = reader.parse('more like The Martain but something funny')
        self.assertEqual((missing['intent'], missing['reason']), ('unknown', 'not_found'))  # left for the agent
        topic = reader.parse('something sad about space')
        self.assertEqual((topic['intent'], topic['parser']), ('search', 'rules+student'))
        self.assertEqual(topic['patch'], {'mood': 'reflective'})
        self.assertEqual(reader.parse('i had a rough day, cheer me up')['intent'], 'session')  # no junk word search

    def test_off_topic_requests_change_nothing(self):
        self.assertEqual(interpreter().parse('how do i bake bread')['intent'], 'unknown')


if __name__ == '__main__':
    unittest.main()
