from pathlib import Path
import tempfile
import unittest

from flicks.core import Content
from flicks.search import TitleIndex
from helpers import app_client


def title(key, name, year=2000, genres=('drama',), tags=('quiet',)):
    return Content(key, name, year, 'movie', 100, list(genres), list(tags), ['curious'], 0.5, 'About it')


class TitleIndexTests(unittest.TestCase):
    def setUp(self):
        self.index = TitleIndex([title('a', 'Amélie', 2001, ('comedy', 'romance')),
                                 title('b', 'Alien', 1979, ('horror', 'science-fiction'), ('space', 'creature')),
                                 title('c', 'Aliens', 1986, ('action', 'science-fiction'))])

    def test_every_word_must_match_accents_and_case_ignored(self):
        self.assertEqual([i.id for i in self.index.search('amelie')[0]], ['a'])
        self.assertEqual([i.id for i in self.index.search('ALIEN')[0]], ['b', 'c'])
        self.assertEqual([i.id for i in self.index.search('alien space')[0]], ['b'])
        self.assertEqual([i.id for i in self.index.search('science fiction 1986')[0]], ['c'])
        self.assertEqual(self.index.search('nothing like this')[:2], ([], 0))

    def test_paging_and_filtering(self):
        page, total, _ = self.index.search('', offset=1, limit=1)
        self.assertEqual(([i.id for i in page], total), (['b'], 3))
        page, total, _ = self.index.search('', keep=lambda item: item.year < 2000)
        self.assertEqual(([i.id for i in page], total), (['b', 'c'], 2))

    def test_genres_and_lookup(self):
        self.assertEqual(self.index.genres, ['action', 'comedy', 'horror', 'romance', 'science-fiction'])
        self.assertEqual(self.index.by_id['b'].title, 'Alien')
        self.assertEqual(len(self.index), 3)


class TitlesApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = app_client(Path(self.temp.name))
        self.client, _ = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_state_describes_the_catalogue_without_sending_it(self):
        state = self.client.get('/api/state').json()
        self.assertNotIn('catalog', state)
        self.assertEqual(state['catalog_size'], 36)
        self.assertIn('science-fiction', state['genres'])

    def test_search_filters_by_rating_and_pages(self):
        self.client.post('/api/feedback', json={'id': 'm001', 'value': 1})
        self.client.post('/api/feedback', json={'id': 'm008', 'value': -1})
        self.assertEqual(self.client.get('/api/titles', params={'q': 'arrival'}).json()['items'][0]['id'], 'm001')
        self.assertEqual([i['id'] for i in self.client.get('/api/titles', params={'show': 'liked'}).json()['items']], ['m001'])
        self.assertEqual([i['id'] for i in self.client.get('/api/titles', params={'show': 'passed'}).json()['items']], ['m008'])
        unrated = self.client.get('/api/titles', params={'show': 'unrated', 'limit': 100}).json()
        self.assertEqual(unrated['total'], 34)
        first, second = (self.client.get('/api/titles', params={'limit': 10, 'offset': o}).json() for o in (0, 10))
        self.assertEqual(first['total'], 36)
        self.assertEqual(len(first['items']), 10)
        self.assertFalse({i['id'] for i in first['items']} & {i['id'] for i in second['items']})

    def test_everyday_search_says_what_it_understood(self):
        reply = self.client.get('/api/titles', params={'q': 'science fiction from the 2010s'}).json()
        self.assertEqual(reply['understood'], ['Science fiction', '2010s'])
        self.assertTrue(reply['items'])
        self.assertTrue(all(2010 <= i['year'] <= 2019 and 'science-fiction' in i['genres'] for i in reply['items']))
        self.assertEqual(self.client.get('/api/titles').json()['understood'], [])

    def test_titles_like_one_title(self):
        reply = self.client.get('/api/titles', params={'similar': 'm007', 'limit': 5}).json()
        self.assertEqual(reply['understood'], ['Like Blade Runner'])
        self.assertNotIn('m007', [i['id'] for i in reply['items']])
        self.assertEqual(reply['total'], 35)
        self.assertEqual(self.client.get('/api/titles', params={'similar': 'nope'}).status_code, 404)

    def test_play_and_search_commands_change_nothing_stored(self):
        for text, intent in (('play Arrival', 'play'), ('science fiction from the 2010s', 'search')):
            with self.subTest(text=text):
                reply = self.client.post('/api/command/apply', json={'text': text}).json()
                self.assertEqual(reply['command']['intent'], intent)
                self.assertEqual(reply['feedback'], {})
                self.assertEqual(reply['session']['mood'], 'any')

    def test_search_input_is_bounded(self):
        for params in ({'limit': 0}, {'limit': 101}, {'offset': -1}, {'show': 'everything'}, {'q': 'x' * 101}, {'similar': 'x' * 65}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get('/api/titles', params=params).status_code, 400)


if __name__ == '__main__':
    unittest.main()
