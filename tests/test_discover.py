import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest import mock

from flicks.core import Session, load_catalog
from flicks.datasets import trailers as trailer_import
from flicks.discover import FOR_YOU, PATTERN, WILDCARD
from flicks.trailers import FORMAT, TrailerIndex
from helpers import CATALOG, app_client

CATALOGUE = load_catalog(CATALOG)
IDS = {item.id for item in CATALOGUE}
GENRES = {item.id: set(item.genres) for item in CATALOGUE}


def write_trailers(path, videos):
    path.write_text(json.dumps({'format': FORMAT, 'trailers': videos}), encoding='utf-8')
    return path


class TrailerIndexTests(unittest.TestCase):
    def test_loads_valid_ids_and_ignores_titles_the_catalogue_lacks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_trailers(Path(folder)/'t.json', {'m001': 'tn2ffzzvC4o', 'gone': 'abcdefghijk'})
            index = TrailerIndex.load(path, IDS)
        self.assertEqual((index.get('m001'), index.get('gone'), len(index)), ('tn2ffzzvC4o', None, 1))

    def test_refuses_a_wrong_format_or_a_bad_video_id(self):
        with tempfile.TemporaryDirectory() as folder:
            for data in ({'format': 'other', 'trailers': {}}, {'format': FORMAT, 'trailers': {'m001': 'x" onload="'}}):
                with self.subTest(data=data):
                    path = Path(folder)/'t.json'
                    path.write_text(json.dumps(data), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        TrailerIndex.load(path, IDS)


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root/'media').mkdir()
        (root/'media'/'m033.webm').write_bytes(b'\x1a\x45\xdf\xa3' + bytes(64))
        trailers = write_trailers(root/'trailers.json', {'m001': 'tn2ffzzvC4o', 'm011': 'xOXyPvqNaIs'})
        self.context = app_client(root, media_dirs=(root/'media',), trailers=trailers)
        self.client, self.services = self.context.__enter__()
        self.discover = self.services.discover

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_a_page_follows_the_stream_pattern_and_never_repeats(self):
        items = self.discover.feed({}, Session(), limit=6)
        self.assertEqual([i['stream'] for i in items], list(PATTERN))
        self.assertEqual(len({i['content']['id'] for i in items}), 6)
        self.assertTrue(all(i['why'] for i in items))

    def test_skips_rated_and_shown_titles(self):
        first = self.discover.feed({}, Session(), limit=6)
        shown = [i['content']['id'] for i in first]
        feedback = {shown[0]: 1, shown[1]: -1}
        second = self.discover.feed(feedback, Session(), seen=shown, limit=6)
        self.assertFalse({i['content']['id'] for i in second} & (set(shown) | set(feedback)))

    def test_a_wildcard_is_in_genres_neither_rated_nor_shown(self):
        feedback = {'m001': 1, 'm011': 1}  # science fiction, drama; comedy, family
        items = self.discover.feed(feedback, Session(), limit=6)
        known = set().union(*(GENRES[k] for k in feedback))
        for index, item in enumerate(items):
            if item['stream'] == WILDCARD:
                before = known.union(*(GENRES[i['content']['id']] for i in items[:index]))
                self.assertFalse(before & set(item['content']['genres']), item['content']['title'])
                self.assertIn('haven’t rated', item['why'])
            known |= GENRES[item['content']['id']]

    def test_a_like_reshapes_what_comes_next(self):
        cold = self.discover.feed({}, Session(), limit=8)
        warm = self.discover.feed({'m008': 1, 'm009': 1, 'm010': 1}, Session(), limit=8)  # horror fan
        horror = lambda items: sum('horror' in i['content']['genres'] for i in items if i['stream'] == FOR_YOU)  # noqa: E731
        self.assertGreaterEqual(horror(warm), horror(cold))
        self.assertNotEqual([i['content']['id'] for i in cold], [i['content']['id'] for i in warm])

    def test_each_item_says_what_it_can_play(self):
        items = {i['content']['id']: i['media'] for i in self.discover.feed({}, Session(), limit=36)}
        self.assertEqual(items['m001'], {'kind': None, 'trailer': 'tn2ffzzvC4o'})  # embedded only once allowed
        self.assertEqual(items['m033'], {'kind': 'file', 'trailer': None})         # a preview, offline
        self.assertEqual(items['m002'], {'kind': None, 'trailer': None})           # the poster

    def test_online_prefers_films_with_a_trailer(self):
        offline = [i['content']['id'] for i in self.discover.feed({}, Session(), limit=4)]
        online = [i['content']['id'] for i in self.discover.feed({}, Session(), limit=4, online=True)]
        self.assertTrue({'m001', 'm011'} & set(online) or offline == online)

    def test_any_length(self):
        items = self.discover.feed({}, Session(minutes=60), limit=10)
        self.assertTrue(any(i['content']['minutes'] > 60 for i in items))

    def test_runs_out_gracefully(self):
        seen = [item.id for item in CATALOGUE][:-2]
        self.assertLessEqual(len(self.discover.feed({}, Session(), seen=seen, limit=8)), 2)


class PickTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = app_client(Path(self.temp.name))
        self.client, self.services = self.context.__enter__()
        self.discover = self.services.discover

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_a_pick_from_the_top_reports_its_chance(self):
        top = [p['content']['id'] for p in self.services.recommender.recommend({}, Session(), limit=12)]
        chances = {}
        for seed in range(40):
            result = self.discover.pick({}, Session(), 'picks', rng=random.Random(seed))
            self.assertIn(result['pick']['content']['id'], top)
            self.assertEqual(result['pool'], 12)
            chances[result['pick']['content']['id']] = result['chance']
        self.assertGreater(len(chances), 1)  # random, not always the top pick
        first = mock.Mock(choices=lambda population, weights: [0])  # always the top pick
        best = self.discover.pick({}, Session(), 'picks', rng=first)
        self.assertEqual(best['pick']['content']['id'], top[0])
        self.assertGreater(best['chance'], 1 / 12)  # the best pick is likelier than a uniform draw
        self.assertGreaterEqual(best['chance'], max(chances.values()))

    def test_anything_is_uniform_over_what_the_scene_allows(self):
        result = self.discover.pick({'m001': 1}, Session(minutes=100), 'anything', rng=random.Random(1))
        allowed = [i for i in CATALOGUE if i.minutes <= 100 and i.id != 'm001']
        self.assertEqual(result['pool'], len(allowed))
        self.assertAlmostEqual(result['chance'], 1 / len(allowed))

    def test_nothing_fits(self):
        genres = sorted({g for item in CATALOGUE for g in item.genres})
        with self.assertRaises(ValueError):
            self.discover.pick({}, Session(excluded_genres=genres[:20]) if len(genres) <= 20 else Session(minutes=1))


class ApiTests(unittest.TestCase):
    def test_discover_and_pick_endpoints(self):
        with tempfile.TemporaryDirectory() as folder, app_client(Path(folder)) as (client, _):
            page = client.post('/api/discover', json={'session': {'mood': 'relaxing'}, 'limit': 4}).json()
            self.assertEqual(len(page['items']), 4)
            seen = [i['content']['id'] for i in page['items']]
            again = client.post('/api/discover', json={'seen': seen, 'limit': 4}).json()
            self.assertFalse(set(seen) & {i['content']['id'] for i in again['items']})
            pick = client.post('/api/pick', json={'pool': 'anything'}).json()
            self.assertIn(pick['pick']['content']['id'], IDS)
            self.assertEqual(client.post('/api/pick', json={'pool': 'everything'}).status_code, 400)
            self.assertEqual(client.post('/api/discover', json={'seen': ['m001'] * 301}).status_code, 400)
            self.assertEqual(client.post('/api/discover', json={'limit': 50}).status_code, 400)
            self.assertEqual(client.get('/api/state').json()['trailers'], 0)

    def test_only_the_host_app_may_frame_youtube_nocookie(self):
        with tempfile.TemporaryDirectory() as folder, app_client(Path(folder)) as (client, _):
            policy = client.get('/').headers['content-security-policy']
        self.assertIn('frame-src https://www.youtube-nocookie.com', policy)
        self.assertNotIn('youtube.com ', policy)


class ImportTests(unittest.TestCase):
    CSV = ('youtubeId,movieId,title\n'
           'tn2ffzzvC4o,1,"Arrival (2016)"\n'
           'zzzzzzzzzzz,1,"Arrival (2016)"\n'      # a second trailer: the first is kept
           'xOXyPvqNaIs,2,"Paddington (2014)"\n'
           'bad id,3,"Broken (2000)"\n'
           'q8nnFkNrzEU,4,"Matrix, The (1999)"\n')

    def test_parses_rows_and_skips_malformed_ones(self):
        rows = trailer_import.read_trailers(self.CSV)
        self.assertEqual([r[0] for r in rows], [1, 1, 2, 4])
        self.assertEqual(rows[-1][2:], ('The Matrix', 1999))

    def test_matches_by_title_and_year_or_by_movielens_id(self):
        rows = trailer_import.read_trailers(self.CSV)
        self.assertEqual(trailer_import.match(CATALOGUE, rows), {'m001': 'tn2ffzzvC4o', 'm011': 'xOXyPvqNaIs'})
        ml = [mock.Mock(id='ml1', audio=False), mock.Mock(id='ml4', audio=False), mock.Mock(id='ml9', audio=False)]
        self.assertEqual(trailer_import.match(ml, rows), {'ml1': 'tn2ffzzvC4o', 'ml4': 'q8nnFkNrzEU'})

    def test_verify_keeps_only_embeddable_videos(self):
        found = {'a': 'tn2ffzzvC4o', 'b': 'zzzzzzzzzzz'}
        kept = trailer_import.verify(found, check=lambda video: video != 'zzzzzzzzzzz', log=lambda _: None)
        self.assertEqual(kept, {'a': 'tn2ffzzvC4o'})

    def test_a_checksum_mismatch_stops_the_import(self):
        replies = {trailer_import.CHECKSUM_URL: b'MD5 (ml-youtube.zip) = ' + b'0' * 32, trailer_import.ARCHIVE_URL: b'zip'}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(trailer_import.net, 'get', side_effect=lambda url, *a, **k: replies[url]), \
                self.assertRaisesRegex(ValueError, 'checksum'):
            trailer_import.download(Path(folder), log=lambda _: None)


if __name__ == '__main__':
    unittest.main()
