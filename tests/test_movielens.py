"""MovieLens importer tests. No network: downloads and Wikimedia lookups are replaced with fixtures."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from flicks.core import load_catalog
from flicks.datasets import genres, movielens, wikimedia

MOVIES = '''movieId,title,genres
1,Toy Story (1995),Adventure|Animation|Children|Comedy|Fantasy
2,"Matrix, The (1999)",Action|Sci-Fi|Thriller
3,"City of Lost Children, The (Cité des enfants perdus, La) (1995)",Adventure|Drama|Fantasy|Mystery|Sci-Fi
4,Seven (a.k.a. Se7en) (1995),Mystery|Thriller
5,Untitled Project,Drama
6,Only Format (2010),IMAX
7,No Runtime (2001),Comedy
8,Not On Wikidata (2002),Comedy
'''
LINKS = '''movieId,imdbId,tmdbId
1,0114709,862
2,0133093,603
3,0112682,902
4,0114369,807
5,1111111,1
6,2222222,2
7,0333333,3
8,0444444,4
'''
TAGS = '''userId,movieId,tag,timestamp
1,1,pixar,1
2,1,Pixar,2
3,1,fun,3
1,2,cyberpunk,4
1,2,"a tag that is far too long to be useful here",5
'''
FILMS = {
    'tt0114709': {'minutes': 81, 'article': 'Toy Story', 'description': '1995 animated film'},
    'tt0133093': {'minutes': 136, 'article': 'The Matrix', 'description': '1999 film'},
    'tt0112682': {'minutes': 112, 'article': None, 'description': '1995 film by Jeunet and Caro'},
    'tt0114369': {'minutes': 127, 'article': 'Seven (1995 film)', 'description': '1995 film'},
    'tt0333333': {'minutes': None, 'article': 'No Runtime', 'description': 'a film'},
}
INTROS = {
    'Toy Story': 'Toy Story is a 1995 American animated comedy film (pronounced /tɔ\u026a/). It follows toys that come to life.',
    'The Matrix': 'The Matrix is a 1999 science fiction action film. A hacker learns the truth about reality.',
    'Seven (1995 film)': 'Seven is a 1995 crime thriller film.',
}


def write_dataset(folder: Path):
    folder.mkdir(parents=True)
    for name, text in (('movies.csv', MOVIES), ('links.csv', LINKS), ('tags.csv', TAGS), ('ratings.csv', 'userId,movieId,rating,timestamp\n')):
        (folder/name).write_text(text, encoding='utf-8')


def archive_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, text in (('movies.csv', MOVIES), ('links.csv', LINKS), ('tags.csv', TAGS)):
            archive.writestr(f'{movielens.DATASET}/{name}', text)
    return buffer.getvalue()


class TitleTests(unittest.TestCase):
    def test_titles(self):
        cases = {
            'Toy Story (1995)': ('Toy Story', 1995),
            'Matrix, The (1999)': ('The Matrix', 1999),
            'City of Lost Children, The (Cité des enfants perdus, La) (1995)': ('The City of Lost Children', 1995),
            'Seven (a.k.a. Se7en) (1995)': ('Seven', 1995),
            "Homme d'à côté, L' (1981)": ("L'Homme d'à côté", 1981),
            'Babylon 5 (1993-1998)': ('Babylon 5', 1993),
            'Untitled Project': ('Untitled Project', None),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(movielens.parse_title(raw), expected)


class GenreTests(unittest.TestCase):
    def test_vocabulary(self):
        self.assertEqual(genres.normalize_genres(['Sci-Fi', 'Children', 'IMAX', 'Sci-Fi', '(no genres listed)']),
                         ['science-fiction', 'family'])

    def test_estimates(self):
        self.assertEqual(genres.estimate(['horror']), (['tense'], 0.9))
        moods, intensity = genres.estimate(['comedy', 'horror'])
        self.assertEqual(set(moods), {'tense', 'uplifting'})  # a tie; broken by a fixed mood order
        self.assertEqual(intensity, 0.78)  # leans toward the most intense genre
        moods, intensity = genres.estimate(['animation', 'family', 'comedy'])
        self.assertEqual(moods, ['uplifting', 'relaxing'])
        self.assertLess(intensity, 0.35)
        with self.assertRaises(ValueError):
            genres.estimate(['short'])

    def test_every_mapped_genre_has_a_profile(self):
        # Film genres and podcast categories together: every mapped genre has a profile, and no profile is unused.
        self.assertEqual(set(genres.GENRE_NAMES.values()) | set(genres.PODCAST_CATEGORIES.values()), set(genres.PROFILES))


class WikimediaTests(unittest.TestCase):
    def test_film_rows_merge_into_one_record(self):
        found = {}
        wikimedia.merge_film_rows(found, [
            {'imdb': {'value': 'tt1'}, 'seconds': {'value': '9000'}, 'article': {'value': 'https://en.wikipedia.org/wiki/Am%C3%A9lie'}},
            {'imdb': {'value': 'tt1'}, 'seconds': {'value': '7320'}, 'itemDescription': {'value': '2001 film'}},
            {'imdb': {'value': 'tt1'}, 'seconds': {'value': '60000'}},  # 1000 minutes: implausible, ignored
            {'imdb': {'value': 'tt2'}},
        ])
        self.assertEqual(found['tt1'], {'minutes': 122, 'article': 'Amélie', 'description': '2001 film'})
        self.assertEqual(found['tt2'], {'minutes': None, 'article': None, 'description': None})

    def test_introductions_follow_normalization_and_redirects(self):
        reply = {'query': {'normalized': [{'from': 'toy Story', 'to': 'Toy Story'}],
                           'redirects': [{'from': 'Se7en', 'to': 'Seven (1995 film)'}],
                           'pages': [{'title': 'Toy Story', 'extract': 'Toys.'}, {'title': 'Seven (1995 film)', 'extract': 'Crime.'},
                                     {'title': 'Gone', 'missing': True}]}}
        with mock.patch.object(wikimedia, 'get_json', return_value=reply), mock.patch.object(wikimedia.time, 'sleep'):
            found = wikimedia.introductions(['toy Story', 'Se7en', 'Gone'], log=lambda *_: None)
        self.assertEqual(found, {'toy Story': 'Toys.', 'Se7en': 'Crime.'})

    def test_imdb_ids_are_validated_before_building_a_query(self):
        with self.assertRaises(ValueError):
            wikimedia.films_by_imdb(['tt0114709" } DROP'], log=lambda *_: None)

    def test_clean_description(self):
        self.assertEqual(wikimedia.clean_description('Toy Story (pronounced /tɔ\u026a/) is a film.  It has toys.'),
                         'Toy Story is a film. It has toys.')
        long = ' '.join(f'Sentence number {i} is here.' for i in range(40))
        self.assertLessEqual(len(wikimedia.clean_description(long)), wikimedia.DESCRIPTION_CHARS)
        self.assertTrue(wikimedia.clean_description(long).endswith('.'))


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_build_catalog_rows_and_skip_reasons(self):
        folder = self.root/'data'
        write_dataset(folder)
        movies, skipped = movielens.read_movies(folder)
        self.assertEqual(skipped, {'no year in the MovieLens title': 1, 'no genres': 1})
        rows, build_skipped = movielens.build_catalog(movies, movielens.read_links(folder), movielens.read_tags(folder), FILMS, INTROS)
        self.assertEqual(build_skipped, {'no runtime on Wikidata': 1, 'not found on Wikidata': 1})
        by_id = {row['id']: row for row in rows}
        self.assertEqual(sorted(by_id), ['ml1', 'ml2', 'ml3', 'ml4'])
        self.assertEqual(by_id['ml1']['tags'], ['pixar', 'fun'])
        self.assertEqual(by_id['ml1']['description'], 'Toy Story is a 1995 American animated comedy film. It follows toys that come to life.')
        self.assertEqual(by_id['ml3']['description'], '1995 film by Jeunet and Caro')  # Wikidata fallback
        self.assertEqual(by_id['ml2']['tags'], ['cyberpunk'])                        # overlong tag dropped
        self.assertEqual(by_id['ml4']['tags'], ['mystery', 'thriller'])              # no tags: genres
        self.assertEqual((by_id['ml2']['title'], by_id['ml2']['minutes']), ('The Matrix', 136))

    def test_download_verifies_the_published_checksum(self):
        data = archive_bytes()
        good = f'MD5 (ml-latest-small.zip) = {hashlib.md5(data).hexdigest()}\n'.encode()
        responses = {movielens.CHECKSUM_URL: good, movielens.ARCHIVE_URL: data}
        with mock.patch.object(movielens.net, 'get', side_effect=lambda url, *a, **k: responses[url]) as get:
            folder = movielens.download(self.root, log=lambda *_: None)
            self.assertTrue((folder/'movies.csv').is_file())
            movielens.download(self.root, log=lambda *_: None)  # already verified: only the checksum is fetched
            self.assertEqual([c.args[0] for c in get.call_args_list].count(movielens.ARCHIVE_URL), 1)
        bad = {movielens.CHECKSUM_URL: b'MD5 (x) = ' + b'0' * 32, movielens.ARCHIVE_URL: data}
        with mock.patch.object(movielens.net, 'get', side_effect=lambda url, *a, **k: bad[url]), \
                self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            movielens.download(self.root/'other', log=lambda *_: None)

    def test_archives_with_unsafe_paths_are_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('../escape.csv', 'x')
        data = buffer.getvalue()
        responses = {movielens.CHECKSUM_URL: f'MD5 = {hashlib.md5(data).hexdigest()}'.encode(), movielens.ARCHIVE_URL: data}
        with mock.patch.object(movielens.net, 'get', side_effect=lambda url, *a, **k: responses[url]), \
                self.assertRaisesRegex(ValueError, 'Unexpected path'):
            movielens.download(self.root, log=lambda *_: None)
        self.assertFalse((self.root.parent/'escape.csv').exists())

    def test_full_import_writes_a_valid_catalogue_and_resumes_from_caches(self):
        cache, out = self.root/'cache', self.root/'catalogs'/'movielens-small.json'
        write_dataset(cache/movielens.DATASET)
        (cache/movielens.DATASET/'.md5').write_text('f' * 32 + '\n', encoding='utf-8')
        films = mock.Mock(side_effect=lambda ids, **_: {i: FILMS[i] for i in ids if i in FILMS})
        intros = mock.Mock(side_effect=lambda articles, **_: {a: INTROS[a] for a in articles if a in INTROS})
        with mock.patch.object(movielens.net, 'get', return_value=b'MD5 = ' + b'f' * 32), \
                mock.patch.object(wikimedia, 'films_by_imdb', films), mock.patch.object(wikimedia, 'introductions', intros):
            result = movielens.import_movielens(out, cache, log=lambda *_: None)
            self.assertEqual(len(load_catalog(out)), 4)
            self.assertEqual(result['titles'], 4)
            self.assertIn('Harper', result['citation'])
            provenance = json.loads(out.with_suffix('.provenance.json').read_text(encoding='utf-8'))
            self.assertEqual(provenance['skipped']['not found on Wikidata'], 1)
            movielens.import_movielens(out, cache, log=lambda *_: None)  # everything cached now
        self.assertEqual(films.call_count, 1)
        self.assertEqual(intros.call_count, 1)


    def test_an_interrupted_lookup_resumes_where_it_stopped(self):
        path = self.root/'cache.json'
        calls = []

        def flaky(keys, **_):
            calls.append(list(keys))
            if len(calls) == 2:
                raise OSError('network dropped')
            return {k: f'value {k}' for k in keys if k != 'b'}

        with mock.patch.object(movielens, 'SAVE_EVERY', 1), self.assertRaises(OSError):
            movielens._cached_lookup(path, ['a', 'b', 'c'], flaky, 'test', lambda *_: None)
        result = movielens._cached_lookup(path, ['a', 'b', 'c'], flaky, 'test', lambda *_: None)
        self.assertEqual(calls, [['a'], ['b'], ['b', 'c']])  # 'a' was saved before the failure
        self.assertEqual(result, {'a': 'value a', 'c': 'value c'})  # 'b' is cached as not found
        self.assertIsNone(json.loads(path.read_text(encoding='utf-8'))['b'])

if __name__ == '__main__':
    unittest.main()
