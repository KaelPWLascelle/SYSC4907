from pathlib import Path
import tempfile
import unittest

from flicks.core import load_catalog
from flicks.media import MediaLibrary, normalize
from helpers import CATALOG, app_client

VIDEO = bytes(range(256)) * 40  # 10 KiB of distinguishable bytes; the server never decodes media


class MediaLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = load_catalog(CATALOG)

    def tearDown(self):
        self.temp.cleanup()

    def touch(self, relative, data=b'video'):
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_matches_ids_and_jellyfin_style_names(self):
        self.touch('m033.webm')
        self.touch('Sherlock Jr. (1924)/Sherlock Jr. (1924).mp4')
        self.touch('The General [1926] 1080p.mkv')
        self.touch('Amelie (2001).m4v')                     # accents optional
        self.touch("Singin' in the Rain (1952).mp4")        # straight vs curly apostrophe
        library = MediaLibrary([self.root], self.catalog)
        self.assertEqual(library.ids(), ['m020', 'm022', 'm033', 'm034', 'm036'])
        self.assertFalse(library.get('m036').direct_play)   # MKV: the UI warns
        self.assertTrue(library.get('m034').direct_play)
        self.assertEqual(library.get('m034').media_type, 'video/mp4')

    def test_wrong_year_unknown_hidden_and_non_video_files_are_skipped(self):
        self.touch('Sherlock Jr. (1999).mp4')               # wrong year: not this film
        self.touch('Home Video (2020).mp4')
        self.touch('.cache/m033.webm')                      # hidden folder
        self.touch('m034.txt')
        library = MediaLibrary([self.root], self.catalog)
        self.assertEqual(library.ids(), [])
        self.assertEqual({p.name for p in library.unmatched}, {'Sherlock Jr. (1999).mp4', 'Home Video (2020).mp4'})

    def test_bare_titles_must_be_unambiguous_and_first_file_wins(self):
        self.touch('Moon.mp4')
        self.touch('a/m034.mp4')
        self.touch('b/m034.webm')
        library = MediaLibrary([self.root, self.root/'missing-folder'], self.catalog)
        self.assertEqual(library.ids(), ['m004', 'm034'])
        self.assertEqual(library.get('m034').path.name, 'm034.mp4')
        self.assertEqual([p.name for p in library.duplicates], ['m034.webm'])

    def test_normalize(self):
        self.assertEqual(normalize('Amélie'), 'amelie')
        self.assertEqual(normalize('Kiki’s Delivery Service'), normalize("Kiki's Delivery Service"))
        self.assertEqual(normalize('Mad Max: Fury Road'), 'mad max fury road')
        self.assertEqual(normalize('Fast & Furious'), 'fast and furious')


class PlaybackApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        media = Path(self.temp.name)/'media'
        media.mkdir()
        (media/'A Trip to the Moon (1902).webm').write_bytes(VIDEO)
        self.context = app_client(Path(self.temp.name), media_dirs=(media,))
        self.client, self.services = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_state_lists_playable_titles(self):
        self.assertEqual(self.client.get('/api/state').json()['media'], [{'id': 'm033', 'direct_play': True}])

    def test_streams_whole_files_and_byte_ranges(self):
        whole = self.client.get('/media/m033')
        self.assertEqual((whole.status_code, whole.content, whole.headers['content-type']), (200, VIDEO, 'video/webm'))
        self.assertEqual(whole.headers['accept-ranges'], 'bytes')
        part = self.client.get('/media/m033', headers={'Range': 'bytes=100-199'})
        self.assertEqual((part.status_code, part.content), (206, VIDEO[100:200]))
        self.assertEqual(part.headers['content-range'], f'bytes 100-199/{len(VIDEO)}')
        tail = self.client.get('/media/m033', headers={'Range': f'bytes={len(VIDEO) - 10}-'})
        self.assertEqual(tail.content, VIDEO[-10:])
        self.assertEqual(self.client.get('/media/m033', headers={'Range': f'bytes={len(VIDEO) + 5}-'}).status_code, 416)
        head = self.client.head('/media/m033')
        self.assertEqual((head.status_code, head.headers['content-length']), (200, str(len(VIDEO))))

    def test_only_scanned_titles_stream(self):
        for path in ('/media/m001', '/media/zzz', '/media/..%2Fflicks.sqlite3', '/media/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_watch_history_round_trip(self):
        self.assertEqual(self.client.get('/api/history').json(), {'items': []})
        saved = self.client.put('/api/history/m033', json={'position_seconds': 120.5, 'duration_seconds': 840})
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()['resumable'])
        [item] = self.client.get('/api/history').json()['items']
        self.assertEqual((item['content_id'], item['position_seconds'], item['completed']), ('m033', 120.5, False))
        self.assertEqual(self.client.delete('/api/history/m033').status_code, 204)
        self.assertEqual(self.client.get('/api/history').json(), {'items': []})

    def test_watch_history_validation(self):
        for body in ({'position_seconds': -1, 'duration_seconds': 10}, {'position_seconds': 1, 'duration_seconds': 0},
                     {'position_seconds': '1', 'duration_seconds': 10}, {'position_seconds': 1}, {'position_seconds': 1, 'duration_seconds': 10, 'x': 1}):
            with self.subTest(body=body):
                self.assertEqual(self.client.put('/api/history/m033', json=body).status_code, 400)
        self.assertEqual(self.client.put('/api/history/zzz', json={'position_seconds': 1, 'duration_seconds': 10}).status_code, 404)
        self.assertEqual(self.client.delete('/api/history/m033', headers={'Origin': 'http://evil.example'}).status_code, 403)
        self.assertEqual(self.client.put('/api/history/m033', content='{}', headers={'Content-Type': 'text/plain'}).status_code, 415)


class ChunkedUploadTests(unittest.TestCase):
    def test_bodies_without_content_length_are_still_capped(self):
        with tempfile.TemporaryDirectory() as folder, app_client(Path(folder)) as (client, _):
            def chunks():
                for _ in range(10):
                    yield b' ' * 1000  # 10 kB, over the 8 KiB JSON limit, with no Content-Length header
            response = client.post('/api/recommend', content=chunks(), headers={'Content-Type': 'application/json'})
            self.assertEqual(response.status_code, 413)


if __name__ == '__main__':
    unittest.main()
