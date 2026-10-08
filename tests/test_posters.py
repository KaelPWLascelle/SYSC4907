import http.client
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from flicks import posters
from flicks.api.guest import create_guest_app
from flicks.api.server import ServerThread
from flicks.core import Content
from flicks.couch import CouchSession
from flicks.posters import PosterLibrary, plausible, sniff
from helpers import app_client


def http_request(host, port, path):
    connection = http.client.HTTPConnection(host, port, timeout=10)
    connection.request('GET', path)
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


def row(key):
    return {'content': {'id': key, 'title': key, 'year': 2000, 'kind': 'movie', 'minutes': 90, 'genres': ['Drama'],
                        'tags': ['t'], 'moods': ['curious'], 'intensity': .5, 'description': 'd'}}

JPEG = b'\xff\xd8\xff\xe0' + b'0' * 64
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64


def item(key, title='Arrival', year=2016):
    return Content(key, title, year, 'movie', 116, ['Drama'], ['x'], ['curious'], .5, 'About it')


def write_cache(directory, entries, files):
    for name, data in files.items():
        (directory/name).write_bytes(data)
    (directory/'posters.json').write_text(json.dumps({'posters': entries}), encoding='utf-8')


class PosterLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_only_catalogue_ids_with_their_own_file_are_served(self):
        outside = Path(self.temp.name).parent/'secret.jpg'
        write_cache(self.dir, {
            'm001': {'file': 'm001.jpg'},
            'm002': {'file': '../secret.jpg'},       # path traversal
            'm003': {'file': 'm001.jpg'},            # someone else's file
            'm004': {'file': 'm004.gif'},            # type we do not serve
            'm005': {'file': 'm005.png'},            # listed but missing on disk
            'zzz': {'file': 'zzz.jpg'},              # not in the catalogue
        }, {'m001.jpg': JPEG, 'm003.jpg': JPEG, 'm004.gif': b'GIF89a', 'zzz.jpg': JPEG})
        library = PosterLibrary(self.dir, {'m001', 'm002', 'm003', 'm004', 'm005'})
        self.assertEqual(library.ids(), ['m001'])
        self.assertEqual(library.read('m001'), (JPEG, 'image/jpeg'))
        self.assertIsNone(library.read('m002'))
        self.assertFalse(outside.exists())

    def test_missing_or_broken_cache_means_no_posters(self):
        self.assertEqual(PosterLibrary(self.dir/'absent', {'m001'}).ids(), [])
        (self.dir/'posters.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(PosterLibrary(self.dir, {'m001'}).ids(), [])

    def test_image_types_come_from_magic_bytes(self):
        self.assertEqual((sniff(JPEG), sniff(PNG), sniff(b'RIFF1234WEBPVP8 ')), ('.jpg', '.png', '.webp'))
        self.assertIsNone(sniff(b'<html>not an image</html>'))

    def test_a_page_must_describe_a_film_from_the_same_year(self):
        self.assertTrue(plausible({'description': '2016 American science fiction drama film'}, item('m001')))
        self.assertFalse(plausible({'description': '1997 American film'}, item('m001')))
        self.assertFalse(plausible({'description': '2016 novel'}, item('m001')))
        self.assertFalse(plausible({}, item('m001')))

    def test_episodes_may_share_their_show_artwork(self):
        write_cache(self.dir, {'p1': {'file': 'show-0123456789ab.jpg'}, 'p2': {'file': 'show-0123456789ab.jpg'},
                               'p3': {'file': 'show-../../x.jpg'}, 'p4': {'file': 'show-nothex.jpg'}},
                    {'show-0123456789ab.jpg': JPEG})
        self.assertEqual(PosterLibrary(self.dir, {'p1', 'p2', 'p3', 'p4'}).ids(), ['p1', 'p2'])

    def test_fetch_downloads_each_image_once_and_rejects_non_images(self):
        jobs = [posters.Job('m001', 'Arrival', 'https://upload.example/a.jpg', 'm001', 'https://en.wikipedia.org/wiki/Arrival_(film)'),
                posters.Job('m002', 'Contact', 'https://upload.example/c', 'm002', None),
                posters.Job('p1', 'Episode 1', 'https://cdn.example/show.png', 'show-0123456789ab', 'https://show.example'),
                posters.Job('p2', 'Episode 2', 'https://cdn.example/show.png', 'show-0123456789ab', 'https://show.example')]
        bodies = {'https://upload.example/a.jpg': JPEG, 'https://upload.example/c': b'<html>', 'https://cdn.example/show.png': PNG}
        calls = []

        def fetch(url, limit, accept='*/*'):
            calls.append(url)
            return bodies[url]

        with mock.patch.object(posters, '_get', side_effect=fetch):
            found, missing = posters.fetch(jobs, self.dir, log=lambda *_: None)
        self.assertEqual((found, missing), (3, 1))
        self.assertEqual(sorted(calls), sorted(bodies))                  # the show's artwork is fetched once
        manifest = json.loads((self.dir/'posters.json').read_text(encoding='utf-8'))
        self.assertEqual(set(manifest['posters']), {'m001', 'p1', 'p2'})
        self.assertEqual(manifest['posters']['p2']['file'], 'show-0123456789ab.png')
        self.assertEqual((self.dir/'m001.jpg').read_bytes(), JPEG)
        self.assertEqual(PosterLibrary(self.dir, {'m001', 'm002', 'p1', 'p2'}).ids(), ['m001', 'p1', 'p2'])
        with mock.patch.object(posters, '_get', side_effect=fetch):     # cached titles are not fetched again
            posters.fetch(jobs, self.dir, log=lambda *_: None)
        self.assertEqual(calls.count('https://upload.example/a.jpg'), 1)

    def test_a_busy_server_is_retried_and_unused_files_are_pruned(self):
        attempts = []

        def busy_then_ok(url, limit, accept='*/*'):
            attempts.append(url)
            if len(attempts) < 3:
                raise posters.error.HTTPError(url, 429, 'Too Many Requests', {'Retry-After': '0'}, None)
            return JPEG

        (self.dir/'m009.jpg').write_bytes(JPEG)                         # left over from an earlier run
        jobs = [posters.Job('m001', 'Arrival', 'https://upload.example/a.jpg', 'm001', None)]
        with mock.patch.object(posters, '_get', side_effect=busy_then_ok), mock.patch.object(posters.time, 'sleep'):
            self.assertEqual(posters.fetch(jobs, self.dir, log=lambda *_: None), (1, 0))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['m001.jpg', 'posters.json'])

    def test_page_images_are_looked_up_in_batches_following_redirects(self):
        def fetch_json(url, params):
            titles = params['titles'].split('|')
            return {'query': {'normalized': [{'from': 'jumanji (film)', 'to': 'Jumanji (film)'}],
                              'redirects': [{'from': 'Toy Story 1', 'to': 'Toy Story'}],
                              'pages': [{'title': 'Toy Story', 'thumbnail': {'source': 'https://upload.example/ts.jpg?utm=x'}},
                                        {'title': 'Jumanji (film)', 'thumbnail': {'source': 'https://upload.example/j.jpg'}},
                                        {'title': 'Nothing', 'missing': True}][:len(titles) + 1]}}
        found = posters.wikipedia_page_images(['Toy Story 1', 'jumanji (film)', 'Nothing'], fetch_json, log=lambda *_: None)
        self.assertEqual(found, {'Toy Story 1': ('https://upload.example/ts.jpg', 'https://en.wikipedia.org/wiki/Toy_Story'),
                                 'jumanji (film)': ('https://upload.example/j.jpg', 'https://en.wikipedia.org/wiki/Jumanji_%28film%29')})


class PosterServingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)/'posters'
        self.dir.mkdir()
        write_cache(self.dir, {'m001': {'file': 'm001.jpg'}, 'm002': {'file': 'm002.png'}}, {'m001.jpg': JPEG, 'm002.png': PNG})

    def tearDown(self):
        self.temp.cleanup()

    def test_host_serves_cached_posters_with_their_type(self):
        with app_client(Path(self.temp.name), poster_dir=self.dir) as (client, _):
            self.assertEqual(client.get('/api/state').json()['posters'], ['m001', 'm002'])
            response = client.get('/posters/m002')
            self.assertEqual((response.status_code, response.content, response.headers['content-type']), (200, PNG, 'image/png'))
            self.assertIn('max-age', response.headers['cache-control'])
            for path in ('/posters/m003', '/posters/../posters.json', '/posters/', '/posters/m001.jpg'):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 404)

    def test_guests_get_posters_for_the_shortlist_only(self):
        library = PosterLibrary(self.dir, {'m001', 'm002', 'm003'})
        session = CouchSession([row('m001'), row('m003')], posters=set(library.ids()))
        self.assertEqual([(i['id'], i['poster']) for i in session.items], [('m001', True), ('m003', False)])
        server = ServerThread(lambda port: create_guest_app(session, '127.0.0.1', port, library), '127.0.0.1', 0).start()
        try:
            status, body, headers = http_request('127.0.0.1', server.port, '/posters/m001')
            self.assertEqual((status, body, headers['content-type']), (200, JPEG, 'image/jpeg'))
            self.assertEqual(http_request('127.0.0.1', server.port, '/posters/m003')[0], 404)  # shortlisted, no poster
            self.assertEqual(http_request('127.0.0.1', server.port, '/posters/m002')[0], 404)  # has a poster, not shortlisted
        finally:
            server.stop()

if __name__ == '__main__': unittest.main()
