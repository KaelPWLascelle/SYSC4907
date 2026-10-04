import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlsplit
from flicks import qr
from flicks.couch import (MAX_FAILED_JOINS, MAX_GUESTS, CouchAuthError, CouchError, CouchManager, CouchSession,
                         check_host, make_guest_server)
from flicks.__main__ import make_server, ROOT


def row(key, title=None):
    content = {'id': key, 'title': title or key, 'year': 2000, 'kind': 'movie', 'minutes': 90, 'genres': ['Drama'],
               'tags': ['secret-tag'], 'moods': ['curious'], 'intensity': .5, 'description': f'About {key}'}
    return {'content': content, 'score': .5, 'factors': {'taste': .5}, 'evidence': ['host-taste-term']}


def http_request(host, port, path, payload=None, headers=None, raw=None):
    connection = http.client.HTTPConnection(host, port, timeout=10)
    body = raw if raw is not None else json.dumps(payload) if payload is not None else None
    connection.request('POST' if body is not None else 'GET', path, body, {'Content-Type': 'application/json', **(headers or {})})
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


class QrTests(unittest.TestCase):
    def test_reed_solomon_codewords_have_zero_syndromes(self):
        divisor = qr._rs_divisor(18)
        data = list(b'http://192.168.1.23:8770/join#K7QX2MPA')
        codeword = data + qr._rs_remainder(data, divisor)
        for i in range(18):  # every root alpha^i of the generator must be a root of the codeword
            x, root = 0, 1
            for _ in range(i):
                root = qr._gf_mul(root, 2)
            for c in codeword:
                x = qr._gf_mul(x, root) ^ c
            self.assertEqual(x, 0)

    def test_format_information_and_finder_patterns(self):
        for text in ('A', 'http://10.0.0.5:8770/join#ABCDEFGH', 'x' * 150):
            with self.subTest(length=len(text)):
                m = qr.encode(text)
                size = len(m)
                self.assertEqual((size - 17) % 4, 0)
                for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
                    self.assertTrue(m[cy][cx] and not m[cy][cx + 2] and m[cy][cx + 3])
                bits = sum(m[i][8] << i for i in range(6)) | m[7][8] << 6 | m[8][8] << 7 | m[8][7] << 8
                bits |= sum(m[8][14 - i] << i for i in range(9, 15))
                data = (bits ^ 0x5412) >> 10
                self.assertEqual(data >> 3, qr.FORMAT_M)  # error-correction level M
                rem = data
                for _ in range(10):
                    rem = (rem << 1) ^ ((rem >> 9) * 0x537)
                self.assertEqual((data << 10 | rem) ^ 0x5412, bits)
                self.assertTrue(m[size - 8][8])  # always-dark module

    def test_single_block_payload_reads_back(self):
        text = 'http://192.168.1.23:8770/join#K7QX2MPA'
        m = qr.encode(text)
        version = (len(m) - 17) // 4
        self.assertEqual(qr.BLOCKS[version - 1], 1)
        b = qr._Builder(version)
        b.draw_function_patterns()
        mask = ((sum(m[i][8] << i for i in range(6)) | m[7][8] << 6 | m[8][8] << 7 | m[8][7] << 8 |
                 sum(m[8][14 - i] << i for i in range(9, 15))) ^ 0x5412) >> 10 & 7
        bits, size = [], len(m)
        for right in range(size - 1, 0, -2):
            if right <= 6:
                right -= 1
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    y = size - 1 - vert if (right + 1) & 2 == 0 else vert
                    if not b.function[y][x]:
                        bits.append(m[y][x] ^ qr.MASKS[mask](x, y))
        stream = ''.join('1' if bit else '0' for bit in bits)
        self.assertEqual(stream[:4], '0100')  # byte mode
        length = int(stream[4:12], 2)
        self.assertEqual(bytes(int(stream[12 + 8 * i:20 + 8 * i], 2) for i in range(length)).decode(), text)

    def test_too_long_and_svg(self):
        with self.assertRaises(ValueError):
            qr.encode('x' * 214)
        image = qr.svg('hello')
        self.assertTrue(image.startswith('<svg') and 'viewBox="0 0 29 29"' in image and '<script' not in image)


class CouchSessionTests(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.session = CouchSession([row('a', 'Alpha'), row('b', 'Beta'), row('c', 'Gamma')], clock=lambda: self.now[0], seconds=100)

    def test_join_needs_the_code_and_wrong_guesses_rotate_it(self):
        with self.assertRaises(CouchAuthError):
            self.session.join('WRONG', 'Sam')
        token, guest = self.session.join(f' {self.session.code.lower()} ', 'Sam')
        self.assertEqual(guest.name, 'Sam')
        self.assertIs(self.session.guest(token), guest)
        old = self.session.code
        for _ in range(MAX_FAILED_JOINS):
            with self.assertRaises(CouchAuthError):
                self.session.join('ZZZZZZZZ', 'Mallory')
        self.assertNotEqual(self.session.code, old)
        with self.assertRaises(CouchAuthError):
            self.session.join(old, 'Late')

    def test_names_are_validated_deduplicated_and_capped(self):
        for bad in ('', '   ', 'x' * 25, 'a\nb', None):
            with self.subTest(name=bad), self.assertRaises(CouchError):
                self.session.join(self.session.code, bad)
        names = [self.session.join(self.session.code, 'Sam')[1].name for _ in range(MAX_GUESTS)]
        self.assertEqual(names[:3], ['Sam', 'Sam 2', 'Sam 3'])
        with self.assertRaises(CouchError):
            self.session.join(self.session.code, 'One more')

    def test_votes_are_validated_hidden_then_revealed_when_everyone_is_done(self):
        sam, _ = self.session.join(self.session.code, 'Sam')
        alex, _ = self.session.join(self.session.code, 'Alex')
        for bad_id, bad_value in (('zzz', 1), ('a', True), ('a', 1.0), ('a', 2), ('a', '1')):
            with self.subTest(value=bad_value), self.assertRaises(CouchError):
                self.session.vote(sam, bad_id, bad_value)
        with self.assertRaises(CouchAuthError):
            self.session.vote('forged', 'a', 1)
        for key, value in (('a', 1), ('b', 1), ('c', -1)):
            self.session.vote(sam, key, value)
        view = self.session.guest_view(alex)
        self.assertFalse(view['revealed'])
        self.assertIsNone(view['results'])
        self.assertEqual(view['you']['votes'], {})  # never another guest's votes
        self.assertEqual([p['voted'] for p in view['progress']], [3, 0])
        for key, value in (('a', -1), ('b', 1), ('c', -1)):
            self.session.vote(alex, key, value)
        results = self.session.guest_view(alex)['results']
        self.assertEqual([r['id'] for r in results], ['b', 'a', 'c'])
        self.assertTrue(results[0]['match'])
        self.assertEqual((results[1]['yes'], results[1]['no']), (1, 1))

    def test_ties_fall_back_to_flicks_ranking_and_votes_can_be_cleared(self):
        sam, _ = self.session.join(self.session.code, 'Sam')
        self.session.vote(sam, 'c', 1)
        self.session.vote(sam, 'c', 0)
        self.assertEqual(self.session.guest_view(sam)['you']['votes'], {})
        self.session.reveal()
        self.assertEqual([r['id'] for r in self.session.host_view()['results']], ['a', 'b', 'c'])

    def test_guests_only_see_public_catalogue_fields(self):
        token, _ = self.session.join(self.session.code, 'Sam')
        view = json.dumps(self.session.guest_view(token))
        for private in ('host-taste-term', 'factors', 'secret-tag', self.session.code):
            self.assertNotIn(private, view)
        self.assertIn('code', self.session.host_view())

    def test_remote_controls_the_player_stub(self):
        token, _ = self.session.join(self.session.code, 'Sam')
        with self.assertRaises(CouchError):
            self.session.remote(token, 'play')
        self.session.remote(token, 'select', 'b')
        self.assertEqual(self.session.player, {'id': 'b', 'state': 'playing', 'by': 'Sam'})
        self.session.control('pause')
        self.assertEqual(self.session.player, {'id': 'b', 'state': 'paused', 'by': 'Host'})
        for action, content_id in (('rewind', None), ('select', 'zzz')):
            with self.assertRaises(CouchError):
                self.session.remote(token, action, content_id)

    def test_sessions_expire(self):
        token, _ = self.session.join(self.session.code, 'Sam')
        self.now[0] = 100
        with self.assertRaises(CouchAuthError):
            self.session.guest(token)
        with self.assertRaises(CouchError):
            self.session.join(self.session.code, 'Late')

    def test_needs_two_titles(self):
        with self.assertRaises(CouchError):
            CouchSession([row('a')])

    def test_only_private_or_loopback_ipv4_addresses(self):
        for good in ('192.168.1.23', '10.0.0.2', '172.20.10.2', '127.0.0.1'):
            self.assertEqual(check_host(good), good)
        for bad in ('8.8.8.8', '0.0.0.0', '169.254.1.1', '::1', 'flicks.local', ''):
            with self.subTest(address=bad), self.assertRaises(CouchError):
                check_host(bad)


class GuestServerTests(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.session = CouchSession([row('a'), row('b')], clock=lambda: self.now[0], seconds=100)
        self.server = make_guest_server(self.session, '127.0.0.1', 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, path, payload=None, headers=None, raw=None):
        return http_request('127.0.0.1', self.server.server_port, path, payload, headers, raw)

    def test_exposes_only_couch_routes(self):
        status, body, headers = self.request('/join')
        self.assertEqual(status, 200)
        self.assertIn(b'couch.js', body)
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        for path in ('/', '/api/state', '/app.js', '/voice.js', '/couch-host.js', '/../couch.py', '/api/couch/qr.svg'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
        for path in ('/api/feedback', '/api/recommend', '/api/command/apply', '/api/transcribe', '/api/couch/start'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, {'id': 'a', 'value': 1})[0], 404)

    def test_host_origin_and_token_checks(self):
        self.assertEqual(self.request('/join', headers={'Host': 'evil.example'})[0], 403)
        code = self.session.code
        self.assertEqual(self.request('/api/couch/join', {'code': code, 'name': 'Sam'}, {'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/couch/join', {'code': 'WRONG', 'name': 'Sam'})[0], 401)
        self.assertEqual(self.request('/api/couch/join', {'code': code, 'name': 'Sam'}, {'Content-Type': 'text/plain'})[0], 400)
        self.assertEqual(self.request('/api/couch/join', raw='x' * 1025)[0], 400)
        status, body, _ = self.request('/api/couch/join', {'code': code, 'name': 'Sam'})
        self.assertEqual(status, 200)
        token = json.loads(body)['token']
        self.assertEqual(self.request('/api/couch/state')[0], 401)
        self.assertEqual(self.request('/api/couch/vote', {'id': 'a', 'value': 1}, {'X-Flicks-Guest': 'forged'})[0], 401)
        status, body, _ = self.request('/api/couch/vote', {'id': 'a', 'value': 1}, {'X-Flicks-Guest': token})
        self.assertEqual((status, json.loads(body)['you']['votes']), (200, {'a': 1}))
        self.assertEqual(self.request('/api/couch/remote', {'action': 'select', 'id': 'a'}, {'X-Flicks-Guest': token})[0], 200)
        self.assertEqual(self.request('/api/couch/vote', {'id': 'zzz', 'value': 1}, {'X-Flicks-Guest': token})[0], 400)
        self.now[0] = 100
        self.assertEqual(self.request('/api/couch/state', headers={'X-Flicks-Guest': token})[0], 410)


class HostCouchApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.couch = CouchManager('127.0.0.1', 0)
        self.server = make_server(ROOT/'data'/'movies.json', Path(self.temp.name)/'test.sqlite3', 0, couch=self.couch)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.couch.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def host(self, path, payload=None, headers=None):
        status, body, _ = http_request('127.0.0.1', self.server.server_port, path, payload, headers)
        return status, json.loads(body) if body[:1] == b'{' else body

    def test_full_couch_session(self):
        self.assertTrue(self.host('/api/state')[1]['couch'])
        self.assertEqual(self.host('/api/couch')[1], {'active': False})
        self.assertEqual(self.host('/api/couch/reveal', {})[0], 400)
        self.host('/api/feedback', {'id': 'm001', 'value': 1})
        status, view = self.host('/api/couch/start', {'session': {'mood': 'relaxing'}})
        self.assertEqual(status, 200)
        self.assertTrue(view['active'])
        self.assertEqual(len(view['items']), 8)
        self.assertNotIn('m001', [item['id'] for item in view['items']])  # rated titles stay out, as in /recommend
        status, image = self.host('/api/couch/qr.svg')
        self.assertTrue(status == 200 and image.startswith(b'<svg'))
        url = urlsplit(view['url'])
        self.assertEqual(view['join_url'], f"{view['url']}#{view['code']}")
        guest = lambda path, payload=None, token='': http_request(url.hostname, url.port, path, payload, {'X-Flicks-Guest': token})
        token = json.loads(guest('/api/couch/join', {'code': view['code'], 'name': 'Sam'})[1])['token']
        self.assertEqual(guest('/api/feedback', {'id': 'm001', 'value': -1}, token)[0], 404)
        for item in view['items']:
            self.assertEqual(guest('/api/couch/vote', {'id': item['id'], 'value': 1 if item is view['items'][2] else -1}, token)[0], 200)
        view = self.host('/api/couch')[1]
        self.assertTrue(view['revealed'])
        self.assertEqual(view['results'][0]['id'], view['items'][2]['id'])
        status, view = self.host('/api/couch/player', {'action': 'select', 'id': view['results'][0]['id']})
        self.assertEqual((status, view['player']['state']), (200, 'playing'))
        self.assertEqual(self.host('/api/couch/player', {'action': 'select', 'id': 'nope'})[0], 400)
        self.assertEqual(self.host('/api/couch/start', {}, {'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.host('/api/couch/stop', {})[1], {'active': False})
        with self.assertRaises(OSError):
            guest('/join')

    def test_couch_routes_are_absent_without_the_flag(self):
        server = make_server(ROOT/'data'/'movies.json', Path(self.temp.name)/'other.sqlite3', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_port
            self.assertFalse(json.loads(http_request('127.0.0.1', port, '/api/state')[1])['couch'])
            self.assertEqual(http_request('127.0.0.1', port, '/api/couch')[0], 404)
            self.assertEqual(http_request('127.0.0.1', port, '/api/couch/start', {})[0], 404)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
