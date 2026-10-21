"""TV series beside films (docs/adr/0018-tv-series.md): the catalogue record, the scene's kind, the
per-kind popularity prior, search and Ask, and the TVmaze import."""
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from flicks import posters
from flicks.assistant.commands import CommandInterpreter
from flicks.collaborative import PopularityPrior
from flicks.core import Content, Recommender, Series, Session, TfidfTaste, load_catalog
from flicks.datasets import tvmaze
from flicks.search import TitleIndex
from helpers import CATALOG, app_client

BREAKING_BAD = {
    'id': 'tv169', 'title': 'Breaking Bad', 'year': 2008, 'kind': 'series', 'minutes': 60,
    'genres': ['crime', 'drama'], 'tags': ['drugs'], 'moods': ['tense', 'reflective'], 'intensity': 0.7,
    'description': 'A chemistry teacher with cancer turns to making drugs.',
    'series': {'seasons': 5, 'episodes': 62, 'ended': 2013, 'network': 'AMC',
               'page': 'https://www.tvmaze.com/shows/169/breaking-bad', 'votes': 2_300_000},
}
BLUEY = {
    'id': 'tv39200', 'title': 'Bluey', 'year': 2018, 'kind': 'series', 'minutes': 7,
    'genres': ['animation', 'family', 'comedy'], 'tags': ['children'], 'moods': ['uplifting', 'relaxing'],
    'intensity': 0.25, 'description': 'A lovable puppy turns everyday family life into play.',
    'series': {'seasons': 3, 'episodes': 154, 'ended': None, 'network': 'ABC Kids',
               'page': 'https://www.tvmaze.com/shows/39200/bluey', 'votes': 40_000},
}


def write(path, rows):
    path.write_text(json.dumps(rows), encoding='utf-8')
    return path


def shows():
    return [Content(**{**row, 'series': Series(**row['series'])}) for row in (BREAKING_BAD, BLUEY)]


def film(key, title, genres=('crime', 'drama'), minutes=100):
    return Content(key, title, 2000, 'movie', minutes, list(genres), ['x'], ['tense'], 0.6, f'About {title}.')


class CatalogueTests(unittest.TestCase):
    def test_series_load_with_their_details(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = load_catalog(write(Path(folder)/'series.json', [BREAKING_BAD, BLUEY]))
        self.assertEqual(catalog[0].series.seasons, 5)
        self.assertTrue(catalog[0].is_series)
        self.assertIsNone(catalog[1].series.ended)  # still running

    def test_kind_and_details_must_agree(self):
        no_details = {k: v for k, v in BREAKING_BAD.items() if k != 'series'}
        cases = {
            'series without details': no_details,
            'details on a film': {**BREAKING_BAD, 'kind': 'movie'},
            'no seasons': {**BREAKING_BAD, 'series': {**BREAKING_BAD['series'], 'seasons': 0}},
            'a page that is not https': {**BREAKING_BAD, 'series': {**BREAKING_BAD['series'], 'page': 'javascript:x'}},
            'votes as text': {**BREAKING_BAD, 'series': {**BREAKING_BAD['series'], 'votes': '9'}},
        }
        for name, row in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
                load_catalog(write(Path(folder)/'series.json', [row]))


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [film('f1', 'Heat'), film('f2', 'Fargo'), *shows()]
        self.recommender = Recommender(self.catalog)

    def ids(self, **scene):
        return {pick['content']['id'] for pick in self.recommender.recommend({}, Session(**scene))}

    def test_the_scene_asks_for_films_series_or_either(self):
        self.assertEqual(self.ids(kind='series'), {'tv169', 'tv39200'})
        self.assertEqual(self.ids(kind='films'), {'f1', 'f2'})
        self.assertEqual(self.ids(), {'f1', 'f2', 'tv169', 'tv39200'})
        with self.assertRaises(ValueError):
            Session(kind='podcasts')

    def test_the_time_limit_is_one_episode(self):
        self.assertEqual(self.ids(minutes=30), {'tv39200'})

    def test_a_liked_crime_film_raises_crime_series(self):
        picks = self.recommender.recommend({'f1': 1}, Session(kind='series'))
        self.assertEqual(picks[0]['content']['id'], 'tv169')


class PopularityTests(unittest.TestCase):
    def test_each_kind_is_scaled_on_its_own(self):
        prior = PopularityPrior(TfidfTaste([film('f1', 'Heat'), film('f2', 'Fargo'), *shows()]),
                                {'f1': 300, 'f2': 3}, {'tv169': 2_300_000, 'tv39200': 40_000})
        # The most-liked film and the most-voted series are equals, though their counts differ 7,000-fold.
        self.assertEqual(prior.popularity['f1'], prior.popularity['tv169'])
        self.assertLess(prior.popularity['tv39200'], prior.popularity['tv169'])

    def test_services_use_the_prior_only_when_films_have_popularity(self):
        with tempfile.TemporaryDirectory() as folder:
            series = write(Path(folder)/'series.json', [BREAKING_BAD, BLUEY])
            with app_client(Path(folder), series=series) as (client, services):
                self.assertFalse(services.popularity_prior)  # the bundled films have none
                self.assertEqual(services.series, 2)
                state = client.get('/api/state').json()
        self.assertEqual(state['series'], 2)
        self.assertEqual(state['catalog_size'], len(load_catalog(CATALOG)) + 2)


class ServicesTests(unittest.TestCase):
    def test_series_are_recommended_and_searched_over_the_api(self):
        with tempfile.TemporaryDirectory() as folder:
            series = write(Path(folder)/'series.json', [BREAKING_BAD, BLUEY])
            with app_client(Path(folder), series=series) as (client, _):
                picks = client.post('/api/recommend', json={'session': {'kind': 'series'}}).json()['recommendations']
                found = client.get('/api/titles', params={'q': 'tv shows'}).json()
                rated = client.post('/api/feedback', json={'id': 'tv169', 'value': 1})
        self.assertEqual({p['content']['id'] for p in picks}, {'tv169', 'tv39200'})
        self.assertIn(picks[0]['content']['series']['network'], ('AMC', 'ABC Kids'))
        self.assertEqual((found['total'], found['understood']), (2, ['Series']))
        self.assertEqual(rated.json()['feedback'], {'tv169': 1})

    def test_ids_shared_with_the_films_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            series = write(Path(folder)/'series.json', [{**BREAKING_BAD, 'id': 'm001'}])
            with self.assertRaises(ValueError), app_client(Path(folder), series=series):
                pass

    def test_video_files_match_films_only(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder)/'media'
            media.mkdir()
            (media/'Breaking Bad (2008).mp4').write_bytes(b'\x00')
            series = write(Path(folder)/'series.json', [BREAKING_BAD])
            with app_client(Path(folder), series=series, media_dirs=(media,)) as (_, services):
                self.assertEqual(services.media.files, {})


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.index = TitleIndex([film('f1', 'Heat'), film('f2', 'The Office Party', ('comedy',)), *shows()])

    def search(self, query):
        items, _, understood = self.index.search(query)
        return [item.id for item in items], understood.labels()

    def test_kind_words(self):
        self.assertEqual(self.search('series'), (['tv169', 'tv39200'], ['Series']))
        self.assertEqual(self.search('tv shows'), (['tv169', 'tv39200'], ['Series']))
        self.assertEqual(self.search('funny sitcoms'), (['tv39200'], ['Comedy', 'Series']))
        self.assertEqual(self.search('crime movies'), (['f1'], ['Crime', 'Films']))
        self.assertEqual(self.search('films and series')[1], [])  # either

    def test_kind_words_narrow_nothing_without_series(self):
        index = TitleIndex([film('f1', 'Heat')])
        self.assertEqual(index.search('crime movies')[2].labels(), ['Crime'])

    def test_popularity_orders_each_kind_on_its_own_scale(self):
        index = TitleIndex(shows(), {'tv169': 1.0, 'tv39200': 0.4})
        self.assertEqual([item.id for item in index.search('')[0]], ['tv169', 'tv39200'])


class AskTests(unittest.TestCase):
    def setUp(self):
        self.rules = CommandInterpreter([film('f1', 'Heat'), *shows()])

    def patch(self, text):
        return self.rules.parse(text).get('patch')

    def test_the_kind_is_read_from_everyday_words(self):
        self.assertEqual(self.patch('something relaxing to binge'), {'mood': 'relaxing', 'kind': 'series'})
        self.assertEqual(self.patch('a show for tonight'), {'kind': 'series'})
        self.assertEqual(self.patch('a tense movie'), {'mood': 'tense', 'kind': 'films'})
        self.assertEqual(self.patch('relaxing, a film or a series'), {'mood': 'relaxing', 'kind': 'any'})
        self.assertEqual(self.rules.parse('a show for tonight')['summary'], 'Set series only.')

    def test_without_series_nothing_reads_a_kind(self):
        rules = CommandInterpreter([film('f1', 'Heat')])
        self.assertEqual(rules.parse('relaxing, 90 minutes, a movie')['patch'], {'mood': 'relaxing', 'minutes': 90})


COVERS = 'https://static.tvmaze.com/uploads/images'


def show(show_id, name, votes_id, **extra):
    return {'id': show_id, 'name': name, 'type': 'Scripted', 'genres': ['Drama', 'Legal'], 'status': 'Ended',
            'runtime': 45, 'averageRuntime': 44, 'premiered': '2010-01-05', 'ended': '2012-05-01',
            'network': {'name': 'BBC One'}, 'webChannel': None, 'url': f'https://www.tvmaze.com/shows/{show_id}/x',
            'externals': {'imdb': votes_id}, 'image': {'medium': f'{COVERS}/medium_portrait/{show_id}.jpg'},
            'summary': f'<p><b>{name}</b> follows a barrister &amp; her clerk. It ran for three years.</p>', **extra}


class FakeTvmaze:
    """TVmaze's API from fixtures: two index pages, then 404; seasons per show."""
    def __init__(self):
        self.pages = [[show(1, 'Silk', 'tt1'), show(2, 'Quiz Night', 'tt2', type='Game Show'),
                       show(3, 'No Votes', 'tt3')],
                      [show(4, 'Line of Duty', 'tt4', genres=['Crime', 'Thriller'], status='Running', ended=None),
                       show(5, 'No Cover', 'tt5', image=None)]]
        self.seasons = {1: [{'episodeOrder': 6, 'premiereDate': '2011-02-22'}, {'episodeOrder': 6, 'premiereDate': '2012-05-01'}],
                        4: [{'episodeOrder': 5, 'premiereDate': '2012-06-26'}, {'episodeOrder': None, 'premiereDate': None}]}
        self.requests = []

    def __call__(self, url):
        self.requests.append(url)
        if '/seasons' in url:
            return self.seasons.get(int(url.split('/')[-2]), [])
        page = int(url.rsplit('=', 1)[1])
        return self.pages[page] if page < len(self.pages) else None


class ImportTests(unittest.TestCase):
    def run_import(self, folder, fake, **options):
        cache = Path(folder)/'cache'
        cache.mkdir()
        with gzip.open(cache/'title.ratings.tsv.gz', 'wt', encoding='utf-8') as ratings:
            ratings.write('tconst\taverageRating\tnumVotes\ntt1\t8.0\t12000\ntt3\t7.0\t10\ntt4\t8.7\t90000\ntt5\t6\t50000\n')
        out = Path(folder)/'series.json'
        result = tvmaze.import_series(out, cache, fetch=fake, log=lambda *_: None, **options)
        return out, result

    def test_builds_a_valid_catalogue_with_artwork_and_provenance(self):
        fake = FakeTvmaze()
        with tempfile.TemporaryDirectory() as folder:
            out, _ = self.run_import(folder, fake)
            catalog = load_catalog(out)
            artwork = json.loads(posters.artwork_path(out).read_text(encoding='utf-8'))
            provenance = json.loads(out.with_suffix('.provenance.json').read_text(encoding='utf-8'))
        self.assertEqual([item.id for item in catalog], ['tv4', 'tv1'])  # most voted first
        duty, silk = catalog
        self.assertEqual((silk.minutes, silk.genres, silk.tags), (44, ['drama'], ['legal']))
        self.assertEqual(silk.description, 'Silk follows a barrister & her clerk. It ran for three years.')
        self.assertEqual(silk.series, Series(2, 12, 2012, 'BBC One', 'https://www.tvmaze.com/shows/1/x', 12000))
        self.assertEqual((duty.series.seasons, duty.series.ended), (1, None))  # unaired seasons do not count
        self.assertEqual(artwork['images']['tv1'], {'image': f'{COVERS}/medium_portrait/1.jpg',
                                                    'full': f'{COVERS}/original_untouched/1.jpg',
                                                    'page': 'https://www.tvmaze.com/shows/1/x'})
        self.assertEqual(provenance['skipped'], {'fewer than 5,000 IMDb votes': 1, 'no cover': 1})
        self.assertEqual((provenance['listed'], provenance['considered']), (5, 4))  # the game show is not kept

    def test_a_rerun_reads_the_cache_and_only_the_last_index_page_again(self):
        fake = FakeTvmaze()
        with tempfile.TemporaryDirectory() as folder:
            self.run_import(folder, fake)
            fake.requests.clear()
            (Path(folder)/'cache'/'title.ratings.tsv.gz').touch()
            tvmaze.import_series(Path(folder)/'series.json', Path(folder)/'cache', fetch=fake, log=lambda *_: None)
        self.assertEqual(fake.requests, [f'{tvmaze.API}/shows?page=1', f'{tvmaze.API}/shows?page=2'])

    def test_limit_keeps_the_most_voted(self):
        with tempfile.TemporaryDirectory() as folder:
            out, result = self.run_import(folder, FakeTvmaze(), limit=1)
            self.assertEqual([item.id for item in load_catalog(out)], ['tv4'])
        self.assertEqual(result['skipped']['beyond the 1 most voted'], 1)

    def test_posters_use_the_full_size_covers(self):
        with tempfile.TemporaryDirectory() as folder:
            out, _ = self.run_import(folder, FakeTvmaze())
            jobs = posters.plan(out, articles={}, fetch_json=self.fail, log=lambda *_: None)
            without_pillow = posters.listed_artwork(out, {'tv1'}, shrink=False)
        self.assertEqual({(job.content_id, job.image, job.page, job.shrink) for job in jobs},
                         {('tv4', f'{COVERS}/original_untouched/4.jpg', 'https://www.tvmaze.com/shows/4/x', True),
                          ('tv1', f'{COVERS}/original_untouched/1.jpg', 'https://www.tvmaze.com/shows/1/x', True)})
        self.assertEqual(without_pillow, {'tv1': (f'{COVERS}/medium_portrait/1.jpg', 'https://www.tvmaze.com/shows/1/x', False)})

    def test_a_full_size_cover_is_cached_at_the_film_posters_width(self):
        from PIL import Image
        original = io.BytesIO()
        Image.new('RGB', (680, 1000), 'navy').save(original, 'PNG')
        job = posters.Job('tv1', 'Silk', f'{COVERS}/original_untouched/1.jpg', 'tv1', None, shrink=True)
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(posters, '_get', return_value=original.getvalue()):
            self.assertEqual(posters.fetch([job], folder, log=lambda *_: None), (1, 0))
            with Image.open(Path(folder)/'tv1.jpg') as cached:
                self.assertEqual((cached.format, cached.size), ('JPEG', (posters.WIDTH, 485)))


if __name__ == '__main__':
    unittest.main()
