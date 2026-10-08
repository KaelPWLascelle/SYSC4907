import json
from pathlib import Path
import tempfile
import unittest
from urllib import error

from fakes import Upstream
from flicks.collaborative import ItemNeighbours, with_prior
from flicks.core import Content, Recommender, Session, load_catalog
from flicks.datasets import podcasts as importer
from flicks.podcasts import FORMAT, Episode, PodcastIndex, PodcastLibrary, episodes_path, sniff_audio
from helpers import app_client

FEED = 'https://example.com/feed.xml'
MP3 = b'ID3\x04\x00' + b'\x00' * 64
RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Deep History</title>
  <link>https://example.com/show</link>
  <description>Long conversations about the past.</description>
  <itunes:category text="History"/>
  <itunes:category text="Society &amp; Culture"><itunes:category text="Philosophy"/></itunes:category>
  <itunes:keywords>Rome, Empires</itunes:keywords>
  <itunes:image href="https://example.com/art.jpg"/>
  <item>
    <title>The Fall of Rome</title>
    <guid>ep-1</guid>
    <pubDate>Tue, 01 Sep 2026 10:00:00 GMT</pubDate>
    <itunes:duration>01:30:05</itunes:duration>
    <enclosure url="https://cdn.example.com/1.mp3" type="audio/mpeg" length="0"/>
    <content:encoded><![CDATA[<p>How an empire <b>ended</b> &amp; what came next.</p>]]></content:encoded>
  </item>
  <item>
    <title>Bonus: Rome Q&amp;A</title>
    <guid>ep-2</guid>
    <pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate>
    <itunes:duration>2700</itunes:duration>
    <enclosure url="https://cdn.example.com/2.m4a" type="audio/x-m4a"/>
    <description>Listener questions.</description>
  </item>
  <item>
    <title>Coming soon</title><itunes:episodeType>trailer</itunes:episodeType>
    <pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate><itunes:duration>2:00</itunes:duration>
    <enclosure url="https://cdn.example.com/t.mp3" type="audio/mpeg"/>
  </item>
  <item>
    <title>Quick update</title><pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate><itunes:duration>9:59</itunes:duration>
    <enclosure url="https://cdn.example.com/q.mp3" type="audio/mpeg"/>
  </item>
  <item>
    <title>Video special</title><pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate><itunes:duration>50:00</itunes:duration>
    <enclosure url="https://cdn.example.com/v.mp4" type="video/mp4"/>
  </item>
  <item>
    <title>Mystery length</title><pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate>
    <enclosure url="https://cdn.example.com/m.mp3" type="audio/mpeg"/>
  </item>
  <item>
    <title>Local file</title><pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate><itunes:duration>50:00</itunes:duration>
    <enclosure url="file:///etc/passwd" type="audio/mpeg"/>
  </item>
</channel>
</rss>""".encode()


def episode(key, minutes=60):
    return Content(key, key.upper(), 2026, 'episode', minutes, ['history'], ['rome'], ['curious'], 0.4,
                   f'About {key}', series='Deep History')


class FeedParsingTests(unittest.TestCase):
    def test_durations_in_every_published_format(self):
        for text, seconds in (('3017', 3017), ('50:51', 3051), ('04:01:20', 14480), ('3017.5', 3017.5), (' 1:00 ', 60)):
            self.assertEqual(importer.parse_duration(text), seconds)
        for text in ('', None, 'an hour', '1:2:3:4', '-5'):
            self.assertIsNone(importer.parse_duration(text))

    def test_keeps_long_form_audio_episodes_newest_first(self):
        show, kept, skipped = importer.parse_feed(RSS, FEED)
        self.assertEqual(show, {'title': 'Deep History', 'feed': FEED, 'link': 'https://example.com/show', 'episodes': 2})
        (first, first_entry), (second, _) = kept
        self.assertEqual(first['title'], 'The Fall of Rome')
        self.assertEqual((first['kind'], first['minutes'], first['year'], first['series']), ('episode', 91, 2026, 'Deep History'))
        self.assertEqual(first['genres'], ['history', 'society-and-culture'])  # top-level categories only
        self.assertEqual(first['tags'], ['rome', 'empires'])
        self.assertEqual(first['description'], 'How an empire ended & what came next.')
        self.assertEqual(first_entry, {'show': 'Deep History', 'feed': FEED, 'link': 'https://example.com/show',
                                       'audio': 'https://cdn.example.com/1.mp3', 'type': 'audio/mpeg', 'published': '2026-09-01',
                                       'image': 'https://example.com/art.jpg'})
        self.assertEqual(second['title'], 'Bonus: Rome Q&A')
        self.assertEqual(dict(skipped), {'trailer': 1, 'shorter than 20 minutes': 1, 'not audio (e.g. a video episode)': 1,
                                         'no duration': 1, 'no audio file': 1})

    def test_ids_are_stable_and_distinct_per_feed(self):
        _, kept, _ = importer.parse_feed(RSS, FEED)
        _, again, _ = importer.parse_feed(RSS, FEED)
        _, elsewhere, _ = importer.parse_feed(RSS, 'https://mirror.example.com/feed.xml')
        self.assertEqual([r['id'] for r, _ in kept], [r['id'] for r, _ in again])
        self.assertTrue(set(r['id'] for r, _ in kept).isdisjoint(r['id'] for r, _ in elsewhere))

    def test_caps_episodes_per_show_and_truncates_notes(self):
        _, kept, skipped = importer.parse_feed(RSS, FEED, per_show=1)
        self.assertEqual(len(kept), 1)
        self.assertEqual(skipped['older than the newest 1'], 1)
        self.assertEqual(importer.truncate('one two three', 9), 'one two…')

    def test_rejects_feeds_flicks_cannot_use(self):
        for data in (b'<html></html>', RSS.replace(b'<title>Deep History</title>', b'<title> </title>'),
                     RSS.replace(b'text="History"', b'text="Nonsense"').replace(b'text="Society &amp; Culture"', b'text="Other"')):
            with self.subTest(data=data[:40]), self.assertRaises(ValueError):
                importer.parse_feed(data, FEED)


class ImportTests(unittest.TestCase):
    def test_writes_a_valid_catalogue_and_index_and_reports_failures(self):
        def fetch(url, limit, accept):
            if 'broken' in url:
                raise error.URLError('no route to host')
            return RSS

        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'podcasts.json'
            logs = []
            result = importer.import_podcasts([FEED, FEED, 'https://broken.example.com/rss', 'ftp://x/feed'], out,
                                              fetch=fetch, log=logs.append)
            self.assertEqual((result['shows'], result['episodes']), (1, 2))
            self.assertEqual(set(result['failed']), {'https://broken.example.com/rss', 'ftp://x/feed'})
            catalogue = load_catalog(out)
            index = PodcastIndex.load(episodes_path(out), {item.id for item in catalogue})
            self.assertEqual(len(index), 2)
            self.assertEqual(index.get(catalogue[0].id).audio, 'https://cdn.example.com/1.mp3')
            with self.assertRaises(ValueError):                    # nothing usable: write nothing
                importer.import_podcasts(['https://broken.example.com/rss'], Path(folder)/'none.json', fetch=fetch, log=logs.append)
            self.assertFalse((Path(folder)/'none.json').exists())


class IndexTests(unittest.TestCase):
    def write(self, folder, episodes):
        path = Path(folder)/'podcasts.episodes.json'
        path.write_text(json.dumps({'format': FORMAT, 'episodes': episodes}), encoding='utf-8')
        return path

    def entry(self, **changes):
        return {'show': 'S', 'feed': FEED, 'link': 'https://example.com', 'audio': 'https://cdn.example.com/a.mp3',
                'type': 'audio/mpeg', 'published': '2026-09-01', **changes}

    def test_ignores_episodes_outside_the_catalogue_and_unsafe_links(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write(folder, {'a': self.entry(link='javascript:alert(1)'), 'gone': self.entry()})
            index = PodcastIndex.load(path, {'a'})
            self.assertEqual((len(index), index.get('a').link), (1, ''))

    def test_rejects_entries_that_could_fetch_anything_but_web_audio(self):
        for bad in (self.entry(audio='file:///etc/passwd'), self.entry(show=''), self.entry(audio=None), 'nope'):
            with self.subTest(entry=bad), tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
                PodcastIndex.load(self.write(folder, {'a': bad}), {'a'})


class PriorCoverageTests(unittest.TestCase):
    def test_titles_the_public_ratings_do_not_cover_keep_their_own_taste(self):
        scores = {'film': {'taste': 0.5, 'familiarity': None}, 'episode': {'taste': 0.6, 'familiarity': None}}
        new = with_prior(scores, {'film': 1.0}, {}, strength=2.0, covered={'film'})
        self.assertEqual(new['film'], {'taste': 1.0, 'familiarity': None, 'popular': True})
        self.assertEqual(new['episode'], {'taste': 0.6, 'familiarity': None, 'popular': False})
        everything = with_prior(scores, {'film': 1.0}, {}, strength=2.0)
        self.assertEqual(everything['episode']['taste'], 0.0)              # without coverage: no data reads as unpopular


class SniffTests(unittest.TestCase):
    def test_recognises_audio_containers_and_nothing_else(self):
        self.assertEqual(sniff_audio(b'ID3\x04'), '.mp3')
        self.assertEqual(sniff_audio(b'\xff\xfb\x90\x00'), '.mp3')      # MPEG-1 layer III frame
        self.assertEqual(sniff_audio(b'\xff\xf1\x50\x80'), '.aac')      # ADTS AAC frame
        self.assertEqual(sniff_audio(b'\x00\x00\x00\x20ftypM4A '), '.m4a')
        self.assertEqual(sniff_audio(b'OggS\x00\x02'), '.ogg')
        for data in (b'<html>', b'', b'\x7fELF', b'\x00\x00\x00\x20ftyp'[:6]):
            self.assertIsNone(sniff_audio(data))


class FakeFetch:
    """Stands in for net.download: writes `body` (or raises `error`) and reports progress."""

    def __init__(self, body=MP3, error=None):
        self.body, self.error, self.calls = body, error, []

    def __call__(self, url, path, limit, progress=None):
        self.calls.append(url)
        if self.error:
            Path(path).write_bytes(b'partial')
            raise self.error
        if len(self.body) > limit:
            raise ValueError('file too large')
        Path(path).write_bytes(self.body)
        if progress:
            progress(len(self.body), len(self.body))
        return len(self.body)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)/'downloads'
        self.index = PodcastIndex({key: Episode(key, 'Deep History', FEED, '', f'https://cdn.example.com/{key}.mp3',
                                                'audio/mpeg', '2026-09-01') for key in ('p1', 'p2')})

    def tearDown(self):
        self.temp.cleanup()

    def library(self, fetch):
        return PodcastLibrary(self.index, self.folder, fetch=fetch)

    def test_downloads_from_the_feed_url_and_names_the_file_by_id(self):
        fetch = FakeFetch()
        library = self.library(fetch)
        self.assertEqual(library.status('p1'), {'state': 'remote'})
        self.assertEqual(library.start('p1')['state'], 'queued')
        library.wait()
        self.assertEqual(fetch.calls, ['https://cdn.example.com/p1.mp3'])
        self.assertEqual(library.status('p1'), {'state': 'ready', 'size': len(MP3)})
        self.assertEqual(library.file('p1').path, self.folder/'p1.mp3')
        self.assertEqual(library.file('p1').media_type, 'audio/mpeg')
        self.assertEqual(library.start('p1')['state'], 'ready')        # already downloaded: no second fetch
        self.assertEqual(len(fetch.calls), 1)
        self.assertEqual(list(library.downloads()), ['p1'])
        self.assertEqual(self.library(FakeFetch()).file('p1').path, self.folder/'p1.mp3')  # found again after a restart

    def test_failures_leave_no_file_and_say_why(self):
        for fetch, reason in ((FakeFetch(body=b'<html>not audio</html>'), 'not MP3'),
                              (FakeFetch(error=error.HTTPError(FEED, 404, 'Not Found', {}, None)), 'the server answered 404'),
                              (FakeFetch(error=error.URLError('timed out')), 'timed out'),
                              (FakeFetch(body=b'ID3' + b'\x00' * 100), 'too large')):
            with self.subTest(reason=reason):
                library = PodcastLibrary(self.index, self.folder, fetch=fetch, limit=64)
                library.start('p2')
                library.wait()
                status = library.status('p2')
                self.assertEqual(status['state'], 'failed')
                self.assertIn(reason, status['error'])
                self.assertEqual(list(self.folder.glob('p2*')), [])
                library.remove('p2')                                     # forget the failure; try again later
                self.assertEqual(library.status('p2'), {'state': 'remote'})

    def test_remove_deletes_the_file_and_unknown_ids_are_refused(self):
        library = self.library(FakeFetch())
        library.start('p1')
        library.wait()
        library.remove('p1')
        self.assertFalse((self.folder/'p1.mp3').exists())
        self.assertEqual(library.status('p1'), {'state': 'remote'})
        for action in (library.start, library.remove):
            with self.assertRaises(ValueError):
                action('m001')

    def test_interrupted_downloads_are_cleaned_up_and_stray_files_ignored(self):
        self.folder.mkdir()
        (self.folder/'p1.part').write_bytes(b'half')
        (self.folder/'other.mp3').write_bytes(MP3)                      # not an episode in the index
        library = self.library(FakeFetch())
        self.assertFalse((self.folder/'p1.part').exists())
        self.assertEqual(library.downloads(), {})


class RankingTests(unittest.TestCase):
    def test_the_scene_chooses_watching_listening_or_either(self):
        film = Content('m1', 'Film', 2020, 'movie', 100, ['history'], ['rome'], ['curious'], 0.4, 'About Rome')
        catalog = [film, episode('p1'), episode('p2')]
        engine = Recommender(catalog)

        def ids(medium):
            return {p['content']['id'] for p in engine.recommend({}, Session(medium=medium))}

        self.assertEqual(ids('any'), {'m1', 'p1', 'p2'})
        self.assertEqual(ids('watch'), {'m1'})
        self.assertEqual(ids('listen'), {'p1', 'p2'})
        with self.assertRaises(ValueError):
            Session(medium='read')

    def test_either_alternates_the_best_films_and_episodes(self):
        films = [Content(f'm{n}', f'F{n}', 2020, 'movie', 100, ['history'], ['rome'], ['curious'], 0.4, 'About Rome')
                 for n in range(4)]
        shows = [Content(f'p{n}', f'E{n}', 2026, 'episode', 60, ['history'], ['rome'], ['curious'], 0.4, 'About Rome',
                         series=f'Show {n}') for n in range(2)]
        picks = Recommender(films + shows).recommend({}, Session())
        kinds = [p['content']['kind'] for p in picks]
        self.assertEqual(kinds, ['movie', 'episode', 'movie', 'episode', 'movie', 'movie'])  # ties: films lead by ID
        # One show with more equally good episodes than the cap allows, ranked ahead of every other title.
        crowded = [Content(f'a{n}', f'A{n}', 2026, 'episode', 60, ['history'], ['rome'], ['curious'], 0.4, 'About Rome',
                           series='Crowded') for n in range(4)]
        mixed = Recommender(films + crowded + shows).recommend({}, Session())
        self.assertEqual([p['content']['kind'] for p in mixed][:6], ['episode', 'movie'] * 3)  # the cap leaves no gaps
        only_films = Recommender(films).recommend({}, Session())
        self.assertEqual([p['content']['id'] for p in only_films], ['m0', 'm1', 'm2', 'm3'])

    def test_picks_hold_at_most_two_episodes_of_one_show(self):
        catalog = [episode(f'p{n}') for n in range(5)] + [
            Content('q1', 'Q', 2026, 'episode', 60, ['science'], ['space'], ['curious'], 0.3, 'Space', series='Other'),
            Content('m1', 'Film', 2020, 'movie', 100, ['history'], ['rome'], ['curious'], 0.4, 'About Rome')]
        picks = Recommender(catalog).recommend({}, Session())
        shows = [p['content']['series'] for p in picks]
        self.assertEqual((shows.count('Deep History'), shows.count('Other'), shows.count(None)), (2, 1, 1))

    def test_series_must_be_text_when_present(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'c.json'
            row = {'id': 'p1', 'title': 'T', 'year': 2026, 'kind': 'episode', 'minutes': 60, 'genres': ['history'],
                   'tags': ['rome'], 'moods': ['curious'], 'intensity': 0.4, 'description': 'D', 'series': ' '}
            path.write_text(json.dumps([row]), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_catalog(path)


class ApiTests(unittest.TestCase):
    def catalogue(self, folder):
        out = Path(folder)/'podcasts.json'
        importer.import_podcasts([FEED], out, fetch=lambda url, limit, accept: RSS, log=lambda _: None)
        return out, [item.id for item in load_catalog(out)]

    def test_episodes_join_the_catalogue_and_download_then_play(self):
        with tempfile.TemporaryDirectory() as folder:
            out, (first, _) = self.catalogue(folder)
            with app_client(Path(folder), podcasts=out, podcast_downloads=Path(folder)/'downloads') as (client, svc):
                svc.podcasts.fetch = FakeFetch()
                svc.streams.opener = upstream = Upstream(MP3)
                state = client.get('/api/state').json()
                self.assertTrue(state['podcasts'])
                self.assertEqual(state['catalog_size'], 38)             # 36 films and 2 episodes
                picks = client.post('/api/recommend', json={'session': {'minutes': 200, 'medium': 'listen'}}).json()
                self.assertEqual({p['content']['kind'] for p in picks['recommendations']}, {'episode'})
                self.assertEqual(picks['recommendations'][0]['content']['series'], 'Deep History')
                info = client.get(f'/api/podcasts/{first}').json()
                self.assertEqual((info['show'], info['download']), ('Deep History', {'state': 'remote'}))
                streamed = client.get(f'/media/{first}')                # not downloaded: streamed from the feed
                self.assertEqual((streamed.status_code, streamed.content), (200, MP3))
                self.assertEqual(upstream.calls[-1][0], 'https://cdn.example.com/1.mp3')

                self.assertEqual(client.post(f'/api/podcasts/{first}/download', json={}).status_code, 202)
                svc.podcasts.wait()
                self.assertEqual(client.get('/api/podcasts/downloads').json()['downloads'][first]['state'], 'ready')
                entry = next(e for e in client.get('/api/state').json()['media'] if e['id'] == first)
                self.assertEqual((entry['audio'], entry['remote'], entry['source']), (True, False, 'Deep History'))
                calls = len(upstream.calls)
                audio = client.get(f'/media/{first}', headers={'Range': 'bytes=0-2'})
                self.assertEqual((audio.status_code, audio.content, audio.headers['content-type']), (206, b'ID3', 'audio/mpeg'))
                self.assertEqual(len(upstream.calls), calls)                 # downloaded: played from disk
                self.assertEqual(client.put(f'/api/history/{first}', json={'position_seconds': 600, 'duration_seconds': 5400}).status_code, 200)
                self.assertEqual(client.delete(f'/api/podcasts/{first}/download').status_code, 204)
                self.assertEqual(client.get(f'/media/{first}').status_code, 200)  # removed: streamed again
                self.assertEqual(len(upstream.calls), calls + 1)

    def test_podcast_routes_refuse_films_and_do_not_exist_without_a_catalogue(self):
        with tempfile.TemporaryDirectory() as folder:
            out, _ = self.catalogue(folder)
            with app_client(Path(folder), podcasts=out, podcast_downloads=Path(folder)/'downloads') as (client, _):
                self.assertEqual(client.post('/api/podcasts/m001/download', json={}).status_code, 404)
                self.assertEqual(client.post('/api/podcasts/m001/download', json={'url': 'x'}).status_code, 400)
            with app_client(Path(folder)/'plain') as (client, _):
                self.assertFalse(client.get('/api/state').json()['podcasts'])
                self.assertEqual(client.get('/api/podcasts/downloads').status_code, 404)

    def test_the_film_popularity_prior_does_not_bury_episodes(self):
        with tempfile.TemporaryDirectory() as folder:
            out, episode_ids = self.catalogue(folder)
            neighbours = Path(folder)/'n.json'
            neighbours.write_text(json.dumps({'format': ItemNeighbours.FORMAT, 'neighbours': {'m001': [['m004', 0.9]]},
                                              'popularity': {'m004': 40, 'm001': 2}}), encoding='utf-8')
            with app_client(Path(folder), podcasts=out, neighbours=neighbours,
                            podcast_downloads=Path(folder)/'downloads') as (client, svc):
                self.assertTrue(svc.popularity_prior)
                picks = client.post('/api/recommend', json={'session': {'minutes': 200}}).json()['recommendations']
                ids = [p['content']['id'] for p in picks]
                self.assertEqual(ids[0], 'm004')                       # the most-liked film leads
                self.assertIn(episode_ids[0], ids[:4])                 # an episode is right behind it
                episode = next(p for p in picks if p['content']['id'] == episode_ids[0])
                self.assertFalse(episode['popular'])
                self.assertAlmostEqual(episode['factors']['taste'], 0.55 * 0.5)  # its own neutral taste, not 0

    def test_a_podcast_catalogue_may_not_reuse_film_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'clash.json'
            row = {'id': 'm001', 'title': 'T', 'year': 2026, 'kind': 'episode', 'minutes': 60, 'genres': ['history'],
                   'tags': ['rome'], 'moods': ['curious'], 'intensity': 0.4, 'description': 'D', 'series': 'S'}
            out.write_text(json.dumps([row]), encoding='utf-8')
            episodes_path(out).write_text(json.dumps({'format': FORMAT, 'episodes': {}}), encoding='utf-8')
            with self.assertRaises(ValueError), app_client(Path(folder), podcasts=out):
                pass


if __name__ == '__main__':
    unittest.main()
