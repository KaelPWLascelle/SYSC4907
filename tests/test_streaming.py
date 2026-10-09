import json
from pathlib import Path
import tempfile
import unittest

from fakes import Upstream
from flicks.archive import FORMAT, ArchiveIndex, archive_path
from flicks.core import Content
from flicks.datasets import archive as importer
from flicks.net import public_web
from flicks.relay import RelayError, Remote, Streams, relay, sniff_video
from helpers import app_client

MP3 = b'ID3\x04\x00' + bytes(range(256)) * 4
MP4 = b'\x00\x00\x00\x20ftypisom' + bytes(range(256)) * 4
EPISODE = Remote('https://cdn.example.com/1.mp3', 'audio/mpeg', True, 'Deep History', 'https://example.com/show')
FILM = Remote('https://archive.org/download/TheGeneral/The_General.mp4', 'video/mp4', False, 'Internet Archive',
              'https://archive.org/details/TheGeneral')


def body(relayed):
    return b''.join(relayed.chunks)


class RelayTests(unittest.TestCase):
    def test_forwards_one_range_and_passes_the_partial_response_on(self):
        upstream = Upstream(MP3)
        relayed = relay(EPISODE, 'bytes=0-9', opener=upstream)
        self.assertEqual(upstream.calls, [('https://cdn.example.com/1.mp3', {'Range': 'bytes=0-9'}, 'GET')])
        self.assertEqual(relayed.status, 206)
        self.assertEqual(relayed.headers['Content-Range'], f'bytes 0-9/{len(MP3)}')
        self.assertEqual(body(relayed), MP3[:10])
        self.assertTrue(upstream.replies[-1].closed)                     # the remote response is closed at the end

    def test_always_labels_the_response_with_the_expected_type(self):
        relayed = relay(EPISODE, opener=Upstream(MP3, content_type='text/html'))  # never trust the remote's type
        self.assertEqual((relayed.status, relayed.headers['Content-Type']), (200, 'audio/mpeg'))
        self.assertEqual(relayed.headers['Cache-Control'], 'no-store')

    def test_refuses_a_file_that_is_not_the_expected_media(self):
        for remote, data in ((EPISODE, b'<html>gotcha</html>'), (FILM, MP3)):
            with self.subTest(source=remote.source), self.assertRaises(RelayError) as caught:
                relay(remote, opener=Upstream(data))
            self.assertEqual(caught.exception.status, 502)
        mid_file = relay(EPISODE, 'bytes=100-199', opener=Upstream(MP3))   # mid-file bytes cannot be sniffed
        self.assertEqual(len(body(mid_file)), 100)

    def test_safari_can_probe_the_first_bytes_before_playing(self):
        # Safari asks for "bytes=0-1" first; too few bytes to recognise, but it must not be refused.
        for remote, data in ((FILM, MP4), (EPISODE, MP3)):
            with self.subTest(source=remote.source):
                relayed = relay(remote, 'bytes=0-1', opener=Upstream(data))
                self.assertEqual((relayed.status, body(relayed), relayed.headers['Content-Range']),
                                 (206, data[:2], f'bytes 0-1/{len(data)}'))
                self.assertEqual(relayed.headers['Content-Type'], remote.media_type)
        with self.assertRaises(RelayError):                                 # 8 bytes are enough to judge
            relay(FILM, 'bytes=0-7', opener=Upstream(b'<html><body>'))

    def test_drops_ranges_browsers_do_not_send(self):
        for header in ('bytes=0-1,5-9', 'items=0-9', 'bytes=abc', '0-9'):
            upstream = Upstream(MP3)
            with self.subTest(header=header):
                self.assertEqual(relay(EPISODE, header, opener=upstream).status, 200)
                self.assertEqual(upstream.calls[-1][1], {})

    def test_remote_failures_become_clear_errors(self):
        for upstream, status, words in ((Upstream(MP3, error_code=404), 502, 'Deep History answered 404'),
                                        (Upstream(MP3, error_code=416), 416, 'does not exist'),
                                        (Upstream(MP3, status=302), 502, 'answered 302')):
            with self.subTest(status=status), self.assertRaises(RelayError) as caught:
                relay(EPISODE, 'bytes=0-1', opener=upstream)
            self.assertEqual(caught.exception.status, status)
            self.assertIn(words, str(caught.exception))

        def offline(url, headers=None, method='GET'):
            raise OSError('network is unreachable')
        with self.assertRaises(RelayError) as caught:
            relay(EPISODE, opener=offline)
        self.assertIn('Check your internet connection', str(caught.exception))

    def test_head_requests_send_headers_only(self):
        upstream = Upstream(MP4)
        relayed = relay(FILM, method='HEAD', opener=upstream)
        self.assertEqual((relayed.status, body(relayed), upstream.calls[-1][2]), (200, b'', 'HEAD'))

    def test_streams_only_titles_it_knows(self):
        with self.assertRaises(RelayError) as caught:
            Streams({'p1': EPISODE}, opener=Upstream(MP3)).open('m001')
        self.assertEqual(caught.exception.status, 404)


class AddressTests(unittest.TestCase):
    def test_only_the_public_web_may_be_fetched(self):
        for url in ('https://archive.org/download/x/y.mp4', 'http://cdn.example.com/a.mp3', 'https://93.184.216.34/a'):
            self.assertTrue(public_web(url), url)
        for url in ('http://localhost/a', 'http://127.0.0.1:8765/api/state', 'http://10.0.0.5/a', 'http://192.168.1.1/',
                    'http://[::1]/x', 'http://169.254.169.254/latest', 'http://router/admin', 'http://printer.local/x',
                    'ftp://example.com/a', 'file:///etc/passwd', 'javascript:alert(1)', 'https:///nohost'):
            self.assertFalse(public_web(url), url)

    def test_video_sniffing(self):
        self.assertEqual(sniff_video(MP4[:16]), '.mp4')
        self.assertEqual(sniff_video(b'\x1a\x45\xdf\xa3\x01'), '.webm')
        for data in (MP3[:16], b'<html>', b''):
            self.assertIsNone(sniff_video(data))


WIKITEXT = """{| class="wikitable"
|-
|''[[Night of the Living Dead]]''{{efn|No copyright notice.}} || 1968 || [[George A. Romero]]
|-
|''[[Charade (1963 film)|Charade]]'' || 1963 || [[Stanley Donen]]
|-
| A row without a linked title || 1950 ||
|}
Prose mentioning ''[[His Girl Friday]]'' (1940) is not a table row."""


def film(key, title, year, minutes=90):
    return Content(key, title, year, 'movie', minutes, ['drama'], ['quiet'], ['curious'], 0.5, f'About {title}')


class RightsTests(unittest.TestCase):
    def test_public_domain_list_reads_table_rows_only(self):
        self.assertEqual(importer.parse_public_domain_list(WIKITEXT), {('night of the living dead', 1968), ('charade', 1963)})

    def test_a_film_qualifies_by_age_or_by_the_list_never_by_the_uploader(self):
        listed = {('night of the living dead', 1968)}
        self.assertEqual(importer.rights_basis(film('a', 'The General', 1926), listed, 2026), 'age')
        self.assertEqual(importer.rights_basis(film('b', 'Animal Crackers', 1930), listed, 2026), 'age')  # 96 years
        self.assertEqual(importer.rights_basis(film('c', 'Night of the Living Dead', 1968), listed, 2026), 'listed')
        self.assertIsNone(importer.rights_basis(film('d', 'Dracula', 1931), listed, 2026))  # copyrighted until 2027

    def test_titles_and_years_from_messy_archive_items(self):
        self.assertEqual(importer.parse_title('Nosferatu (1922) [4K]'), ('nosferatu', 1922))
        self.assertEqual(importer.parse_title(['The General']), ('the general', None))
        self.assertEqual(importer.item_year({'title': 'The General', 'year': ['1927']}), 1927)
        self.assertIsNone(importer.item_year({'title': 'Untitled', 'year': 'unknown'}))

    def test_matches_by_title_and_year_and_skips_versions_that_are_not_the_film(self):
        catalog = [film('a', 'The General', 1926), film('b', 'Dracula', 1931), film('c', 'Metropolis', 1927)]
        items = [{'identifier': 'TheGeneral', 'title': 'The General', 'year': 1927, 'downloads': 10},
                 {'identifier': 'general-hd', 'title': 'The General (1926)', 'downloads': 99},
                 {'identifier': 'general-1990', 'title': 'The General', 'year': 1990, 'downloads': 999},  # other film
                 {'identifier': 'dracula-1931', 'title': 'Dracula (1931)', 'downloads': 5},
                 {'identifier': 'metropolis-colorized', 'title': 'Metropolis (1927)', 'downloads': 50}]
        found, skipped = importer.match(catalog, items, set(), 2026)
        self.assertEqual(list(found), ['a'])
        self.assertEqual([i['identifier'] for i in found['a'][2]], ['general-hd', 'TheGeneral'])  # most downloaded first
        self.assertEqual(skipped, {'on the Archive but not known to be public domain in the US': 1})

    def test_chooses_the_best_complete_browser_playable_file(self):
        files = {'files': [
            {'name': 'film.mpeg', 'format': 'MPEG2', 'length': '4000'},
            {'name': 'film_512kb.mp4', 'format': '512Kb MPEG4', 'length': '4039.1', 'height': '240'},
            {'name': 'film.mp4', 'format': 'h.264', 'length': '1:07:19', 'height': '480'},
            {'name': 'film_trailer.mp4', 'format': 'h.264 HD', 'length': '120'},
        ]}
        self.assertEqual(importer.choose_file(files, minutes=75), ('film.mp4', 4039.0))
        self.assertIsNone(importer.choose_file({'files': [files['files'][3]]}, minutes=75))  # too short to be the film


class ImportTests(unittest.TestCase):
    def test_writes_an_index_the_app_accepts(self):
        catalog = [film('m1', 'The General', 1926, 75), film('m2', 'Nosferatu', 1922, 80), film('m3', 'Dracula', 1931)]
        metadata = {'TheGeneral': {'files': [{'name': 'The General.mp4', 'format': 'h.264', 'length': '4500'}]},
                    'nosferatu-1': {'files': [{'name': 'n.ogv', 'format': 'Ogg Video', 'length': '4800'}]}}

        def fetch(url, limit, accept='*/*', timeout=30):
            if 'scrape' in url:
                return json.dumps({'items': [{'identifier': 'TheGeneral', 'title': 'The General (1926)', 'downloads': 3},
                                             {'identifier': 'nosferatu-1', 'title': 'Nosferatu (1922)', 'downloads': 1},
                                             {'identifier': 'dracula', 'title': 'Dracula (1931)', 'downloads': 9}]}).encode()
            return json.dumps(metadata[url.rsplit('/', 1)[1]]).encode()

        def fetch_json(url, params):
            return {'parse': {'wikitext': WIKITEXT, 'revid': 42}}

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'cat.json'
            path.write_text(json.dumps([{k: v for k, v in item.__dict__.items()} for item in catalog]), encoding='utf-8')
            result = importer.import_archive(path, fetch, fetch_json, log=lambda _: None, pause=0, this_year=2026)
            self.assertEqual(result['films'], 1)
            self.assertEqual(result['skipped'], {'no complete, browser-playable MP4': 1,
                                                 'on the Archive but not known to be public domain in the US': 1})
            written = json.loads(archive_path(path).read_text(encoding='utf-8'))
            self.assertEqual(written['rights']['wikipedia'], 'https://en.wikipedia.org/w/index.php?oldid=42')
            self.assertEqual(written['films']['m1']['url'], 'https://archive.org/download/TheGeneral/The%20General.mp4')
            remote = ArchiveIndex.load(archive_path(path), {'m1'}).remotes()['m1']
            self.assertEqual((remote.media_type, remote.audio, remote.source), ('video/mp4', False, 'Internet Archive'))


class IndexTests(unittest.TestCase):
    def write(self, folder, films):
        path = Path(folder)/'c.archive.json'
        path.write_text(json.dumps({'format': FORMAT, 'films': films}), encoding='utf-8')
        return path

    def test_only_archive_hosted_video_is_accepted(self):
        good = {'url': 'https://archive.org/download/x/x.mp4', 'page': 'https://archive.org/details/x'}
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(len(ArchiveIndex.load(self.write(folder, {'a': good, 'gone': good}), {'a'})), 1)
            for bad in ({**good, 'url': 'https://evil.example.com/x.mp4'}, {**good, 'url': 'http://127.0.0.1/x.mp4'},
                        {**good, 'url': 'https://archive.org/download/x/x.exe'}, {**good, 'page': 'javascript:alert(1)'}):
                with self.subTest(entry=bad), self.assertRaises(ValueError):
                    ArchiveIndex.load(self.write(folder, {'a': bad}), {'a'})


class ApiTests(unittest.TestCase):
    def test_an_archive_film_plays_through_flicks(self):
        with tempfile.TemporaryDirectory() as folder:
            index = Path(folder)/'c.archive.json'
            index.write_text(json.dumps({'format': FORMAT, 'films': {'m001': {
                'url': 'https://archive.org/download/arrival/arrival.mp4', 'page': 'https://archive.org/details/arrival'}}}),
                encoding='utf-8')
            with app_client(Path(folder), archive=index) as (client, svc):
                svc.streams.opener = upstream = Upstream(MP4)
                entry = next(e for e in client.get('/api/state').json()['media'] if e['id'] == 'm001')
                self.assertEqual(entry, {'id': 'm001', 'direct_play': True, 'audio': False, 'remote': True,
                                         'source': 'Internet Archive', 'page': 'https://archive.org/details/arrival'})
                video = client.get('/media/m001', headers={'Range': 'bytes=0-15'})
                self.assertEqual((video.status_code, video.headers['content-type'], video.content), (206, 'video/mp4', MP4[:16]))
                self.assertEqual(upstream.calls[-1][1], {'Range': 'bytes=0-15'})
                self.assertEqual(video.headers['x-content-type-options'], 'nosniff')
                ready = client.post('/api/recommend', json={'session': {'minutes': 200, 'playable': True}}).json()
                self.assertEqual([p['content']['id'] for p in ready['recommendations']], ['m001'])  # only what can play
                upstream.error_code = 503
                failed = client.get('/media/m001')
                self.assertEqual((failed.status_code, failed.json()), (502, {'error': 'Internet Archive answered 503'}))
                self.assertEqual(client.get('/media/m002').status_code, 404)


if __name__ == '__main__':
    unittest.main()
