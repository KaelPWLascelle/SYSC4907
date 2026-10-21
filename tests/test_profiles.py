from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from flicks.core import load_catalog
from flicks.db import Database
from flicks.profiles import MAX_FAILURES, ProfileSessions, plan_import
from flicks.repositories import (
    ProfileRepository,
    RatingsRepository,
    WatchHistoryRepository,
    check_pin,
    hash_pin,
    merge_profile_data,
)
from helpers import CATALOG, app_client

JSON = {'Content-Type': 'application/json'}


class MigrationTests(unittest.TestCase):
    def test_existing_ratings_and_progress_move_to_the_first_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'flicks.sqlite3'
            # A version-2 database exactly as the previous release created it.
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE feedback (content_id TEXT PRIMARY KEY, value INTEGER NOT NULL CHECK (value IN (-1, 1)), '
                           'updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
                db.execute('CREATE TABLE watch_history (content_id TEXT PRIMARY KEY, position_seconds REAL NOT NULL, '
                           'duration_seconds REAL NOT NULL, completed INTEGER NOT NULL DEFAULT 0, started_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
                db.execute("INSERT INTO feedback VALUES ('m001', 1, '2026-01-02 03:04:05')")
                db.execute("INSERT INTO watch_history VALUES ('m004', 120, 900, 0, '2026-01-02T03:04:05.000Z', '2026-01-02T03:04:05.000Z')")
                db.execute('PRAGMA user_version = 2')
            database = Database(path)
            self.assertEqual(RatingsRepository(database).all(), {'m001': 1})
            self.assertEqual(RatingsRepository(database).rows()[0][2], '2026-01-02T03:04:05.000Z')
            self.assertEqual(WatchHistoryRepository(database).get('m004').position_seconds, 120)
            self.assertEqual([p.name for p in ProfileRepository(database).all()], ['Me'])


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name)/'flicks.sqlite3')
        self.profiles = ProfileRepository(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_ratings_and_history_are_separate_per_profile(self):
        other = self.profiles.create('Sam')
        RatingsRepository(self.database).set('m001', 1)
        RatingsRepository(self.database, other.id).set('m008', -1)
        WatchHistoryRepository(self.database, other.id).save('m004', 100, 900)
        self.assertEqual(RatingsRepository(self.database).all(), {'m001': 1})
        self.assertEqual(RatingsRepository(self.database, other.id).all(), {'m008': -1})
        self.assertEqual(WatchHistoryRepository(self.database).recent(), [])
        self.profiles.delete(other.id)  # cascades
        self.assertEqual(RatingsRepository(self.database, other.id).all(), {})
        self.assertEqual(WatchHistoryRepository(self.database, other.id).recent(), [])

    def test_names_pins_and_limits(self):
        with self.assertRaisesRegex(ValueError, 'already'):
            self.profiles.create('me')  # case-insensitive
        for bad in ('', ' ' * 3, 'x' * 41, 'tab\there'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.profiles.create(bad)
        for bad in ('123', '123456789', 'abcd', '12 34'):
            with self.subTest(pin=bad), self.assertRaisesRegex(ValueError, 'PIN'):
                self.profiles.create('Kid', bad)
        kid = self.profiles.create('  Kid   Two ', '2468')
        self.assertEqual(kid.name, 'Kid Two')
        self.assertTrue(kid.locked)
        self.assertTrue(self.profiles.verify(kid.id, '2468'))
        self.assertFalse(self.profiles.verify(kid.id, '1357'))
        self.assertFalse(self.profiles.verify(kid.id, None))
        self.assertEqual(self.profiles.unique_name('kid two'), 'kid two (2)')
        with self.assertRaisesRegex(ValueError, 'at least one'):
            for profile in self.profiles.all():
                self.profiles.delete(profile.id)

    def test_pin_hashes_are_salted(self):
        first, second = hash_pin('1234'), hash_pin('1234')
        self.assertNotEqual(first, second)
        self.assertTrue(check_pin('1234', first) and check_pin('1234', second))
        self.assertNotIn('1234', first)

    def test_merge_keeps_the_newer_row(self):
        ratings = RatingsRepository(self.database)

        def merge(rows):
            return merge_profile_data(self.database, 1, rows, [])[0]
        merge([('m001', 1, '2026-05-01T00:00:00.000Z')])
        self.assertEqual(merge([('m001', -1, '2026-04-01T00:00:00Z')]), 0)  # older: ignored
        self.assertEqual(ratings.all(), {'m001': 1})
        self.assertEqual(merge([('m001', -1, '2026-06-01T00:00:00+00:00')]), 1)
        self.assertEqual(ratings.all(), {'m001': -1})

    def test_sessions_lock_out_after_repeated_wrong_pins(self):
        now = [0.0]
        sessions = ProfileSessions(clock=lambda: now[0])
        for _ in range(MAX_FAILURES):
            self.assertFalse(sessions.attempt(2, lambda: False))
        with self.assertRaisesRegex(PermissionError, 'Too many'):
            sessions.attempt(2, lambda: True)  # even the right PIN waits out the lockout
        now[0] += 61
        self.assertTrue(sessions.attempt(2, lambda: True))  # the lockout expires

    def test_parallel_guesses_cannot_outrun_the_lockout(self):
        sessions = ProfileSessions()

        def guess():
            try:
                return sessions.attempt(2, lambda: time.sleep(0.01) or False)
            except PermissionError:
                return 'locked'
        with ThreadPoolExecutor(16) as pool:
            results = list(pool.map(lambda _: guess(), range(40)))
        self.assertEqual(results.count(False), MAX_FAILURES)  # only five guesses were ever checked
        self.assertEqual(results.count('locked'), 40 - MAX_FAILURES)

    def test_deleted_profile_ids_are_never_reused(self):
        ann = self.profiles.create('Ann')
        self.profiles.delete(ann.id)
        self.assertGreater(self.profiles.create('Bob').id, ann.id)

    def test_import_timestamps_are_bounded(self):
        for bad in ('0001-01-01T00:00:00+01:00', '9999-12-31T23:59:59-05:00', '1900-01-01T00:00:00Z'):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, '1970'):
                merge_profile_data(self.database, 1, [('m001', 1, bad)], [])


class ImportPlanTests(unittest.TestCase):
    catalog = load_catalog(CATALOG)

    def document(self, **overrides):
        return {'format': 'flicks-profile', 'version': 1, 'profile': {'name': 'Sam'},
                'ratings': [{'id': 'm001', 'title': 'Arrival', 'year': 2016, 'value': 1, 'updated_at': '2026-01-01T00:00:00Z'}],
                'history': [], **overrides}

    def test_matches_by_id_then_by_title_and_year(self):
        plan = plan_import(self.document(ratings=[
            {'id': 'm001', 'title': 'Arrival', 'year': 2016, 'value': 1, 'updated_at': '2026-01-01T00:00:00Z'},
            {'id': 'other-catalogue-7', 'title': 'Moon', 'year': 2009, 'value': -1, 'updated_at': '2026-01-01T00:00:00Z'},
            {'id': 'm002', 'title': 'Not Contact', 'year': 1997, 'value': 1, 'updated_at': '2026-01-01T00:00:00Z'},
            {'id': 'zzz', 'value': 1, 'updated_at': '2026-01-01T00:00:00Z'}]), self.catalog)
        self.assertEqual([r[0] for r in plan.ratings], ['m001', 'm004'])
        self.assertEqual(plan.skipped, 2)

    def test_rejects_malformed_documents(self):
        cases = {
            'not a Flicks': {'format': 'other'},
            'Unsupported export version': self.document(version=2),
            'Unknown fields': self.document(weights=[1, 2]),
            'no profile name': self.document(profile={}),
            '1 \\(like\\)': self.document(ratings=[{'id': 'm001', 'value': 5, 'updated_at': '2026-01-01T00:00:00Z'}]),
            'updated_at': self.document(ratings=[{'id': 'm001', 'value': 1, 'updated_at': 'yesterday'}]),
            'known fields': self.document(ratings=[{'id': 'm001', 'value': 1, 'updated_at': '2026-01-01T00:00:00Z', 'x': 1}]),
            'Duration must be positive': self.document(history=[{'id': 'm004', 'position_seconds': -5, 'duration_seconds': 900,
                                                                 'updated_at': '2026-01-01T00:00:00Z'}]),
            '1970': self.document(ratings=[{'id': 'm001', 'value': 1, 'updated_at': '9999-12-31T23:59:59-05:00'}]),
        }
        for message, document in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                plan_import(document, self.catalog)


class ProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = app_client(Path(self.temp.name))
        self.client, self.services = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_default_profile_works_without_choosing(self):
        listing = self.client.get('/api/profiles').json()
        self.assertEqual(listing['current']['name'], 'Me')
        self.assertFalse(listing['chosen'])
        self.client.post('/api/feedback', json={'id': 'm001', 'value': 1})
        self.assertEqual(self.client.get('/api/state').json()['profile']['name'], 'Me')

    def test_profiles_keep_their_own_ratings_history_and_recommendations(self):
        self.client.post('/api/feedback', json={'id': 'm001', 'value': 1})
        created = self.client.post('/api/profiles', json={'name': 'Sam'})
        self.assertEqual(created.status_code, 201)
        self.assertIn('httponly', created.headers['set-cookie'].lower())
        self.assertIn('samesite=strict', created.headers['set-cookie'].lower())
        self.assertEqual(self.client.get('/api/state').json()['feedback'], {})  # signed in as Sam now
        self.client.put('/api/history/m004', json={'position_seconds': 60, 'duration_seconds': 900})
        self.client.post('/api/feedback', json={'id': 'm008', 'value': -1})
        sam = self.client.get('/api/profiles').json()
        self.assertTrue(sam['chosen'])
        self.assertEqual({p['name']: p['ratings'] for p in sam['profiles']}, {'Me': 1, 'Sam': 1})
        self.client.post('/api/profiles/1/select', json={})
        self.assertEqual(self.client.get('/api/state').json()['feedback'], {'m001': 1})
        self.assertEqual(self.client.get('/api/history').json()['items'], [])

    def test_pin_profiles_need_their_pin_and_lock_out(self):
        self.client.post('/api/profiles', json={'name': 'Parent', 'pin': '2468'})
        self.client.post('/api/profiles/signout', json={})
        self.client.cookies.clear()
        parent = 2
        self.assertEqual(self.client.post(f'/api/profiles/{parent}/select', json={}).status_code, 403)
        for _ in range(MAX_FAILURES - 1):
            self.assertEqual(self.client.post(f'/api/profiles/{parent}/select', json={'pin': '0000'}).status_code, 403)
        locked = self.client.post(f'/api/profiles/{parent}/select', json={'pin': '2468'})
        self.assertEqual(locked.status_code, 429)
        self.assertEqual(self.client.post('/api/profiles/99/select', json={}).status_code, 404)

    def test_a_pin_profile_is_never_the_default(self):
        self.client.put('/api/profiles/current', json={'pin': '1357'})
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/state').status_code, 401)
        listing = self.client.get('/api/profiles').json()
        self.assertIsNone(listing['current'])
        self.assertEqual(self.client.post('/api/profiles/1/select', json={'pin': '1357'}).status_code, 200)
        self.assertEqual(self.client.put('/api/profiles/current', json={'pin': None}).status_code, 403)  # needs current PIN
        self.assertEqual(self.client.put('/api/profiles/current', json={'pin': None, 'current_pin': '1357'}).status_code, 200)

    def test_rename_clear_and_delete(self):
        self.assertEqual(self.client.put('/api/profiles/current', json={'name': 'Kael'}).json()['profile']['name'], 'Kael')
        self.client.post('/api/feedback', json={'id': 'm001', 'value': 1})
        self.assertEqual(self.client.delete('/api/profiles/current/data').status_code, 204)
        self.assertEqual(self.client.get('/api/state').json()['feedback'], {})
        self.assertEqual(self.client.delete('/api/profiles/current').status_code, 403)  # not chosen yet
        self.client.post('/api/profiles/1/select', json={})
        self.assertEqual(self.client.delete('/api/profiles/current').status_code, 400)  # the last profile
        self.client.post('/api/profiles', json={'name': 'Sam'})
        self.client.post('/api/feedback', json={'id': 'm002', 'value': 1})
        deleted = self.client.delete('/api/profiles/current')
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual([p['name'] for p in deleted.json()['profiles']], ['Kael'])
        self.assertEqual(self.client.get('/api/state').json()['profile']['name'], 'Kael')

    def test_export_then_import_on_another_device(self):
        self.client.post('/api/feedback', json={'id': 'm001', 'value': 1})
        self.client.post('/api/feedback', json={'id': 'm008', 'value': -1})
        self.client.put('/api/history/m004', json={'position_seconds': 300, 'duration_seconds': 900})
        exported = self.client.get('/api/profiles/current/export')
        self.assertIn('attachment', exported.headers['content-disposition'])
        document = exported.json()
        self.assertEqual(document['format'], 'flicks-profile')
        self.assertEqual({r['id']: r['title'] for r in document['ratings']}, {'m001': 'Arrival', 'm008': 'Alien'})
        with tempfile.TemporaryDirectory() as other, app_client(Path(other)) as (device, _):
            imported = device.post('/api/profiles/import', content=json.dumps(document), headers=JSON)
            self.assertEqual(imported.status_code, 201, imported.text)
            self.assertEqual(imported.json()['ratings'], 2)
            self.assertEqual(imported.json()['profile']['name'], 'Me (2)')  # never collides
            self.assertEqual(device.get('/api/state').json()['feedback'], {'m001': 1, 'm008': -1})
            self.assertEqual(device.get('/api/history').json()['items'][0]['position_seconds'], 300)
            # Importing again into the same profile changes nothing: nothing in the file is newer.
            again = device.post('/api/profiles/import?mode=merge', content=json.dumps(document), headers=JSON)
            self.assertEqual((again.status_code, again.json()['ratings'], again.json()['history']), (200, 0, 0))

    def test_import_is_validated_and_bounded(self):
        bad = self.client.post('/api/profiles/import', content=b'{not json', headers=JSON)
        self.assertEqual(bad.status_code, 400)
        wrong = self.client.post('/api/profiles/import', content=json.dumps({'format': 'x'}), headers=JSON)
        self.assertEqual(wrong.status_code, 400)
        huge = self.client.post('/api/profiles/import', content=b' ' * (2 * 1024 * 1024 + 1), headers=JSON)
        self.assertEqual(huge.status_code, 413)
        self.assertEqual(len(self.client.get('/api/profiles').json()['profiles']), 1)  # nothing half-created

    def test_a_page_for_another_profile_is_refused_instead_of_saving_to_the_wrong_one(self):
        self.client.post('/api/profiles', json={'name': 'Sam'})
        sam = {'X-Flicks-Profile': '2'}
        self.assertEqual(self.client.post('/api/feedback', json={'id': 'm001', 'value': 1}, headers=sam).status_code, 200)
        self.services.sessions.tokens.clear()  # Flicks restarted: the sign-in is gone, the default is "Me"
        refused = self.client.post('/api/feedback', json={'id': 'm002', 'value': 1}, headers=sam)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.headers['x-flicks-profile-changed'], '1')
        self.assertEqual(self.services.ratings.all(), {})  # nothing reached "Me"
        self.assertEqual(self.client.post('/api/feedback', json={'id': 'm002', 'value': 1},
                                          headers={'X-Flicks-Profile': '1'}).status_code, 200)

    def test_a_bad_merge_import_changes_nothing(self):
        document = {'format': 'flicks-profile', 'version': 1, 'profile': {'name': 'Me'},
                    'ratings': [{'id': 'm001', 'value': 1, 'updated_at': '2026-01-01T00:00:00Z'}],
                    'history': [{'id': 'm004', 'position_seconds': -5, 'duration_seconds': 900, 'updated_at': '2026-01-01T00:00:00Z'}]}
        response = self.client.post('/api/profiles/import?mode=merge', content=json.dumps(document), headers=JSON)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/api/state').json()['feedback'], {})

    def test_export_works_for_any_profile_name(self):
        self.client.put('/api/profiles/current', json={'name': '日本 Ünïcode'})
        exported = self.client.get('/api/profiles/current/export')
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()['profile']['name'], '日本 Ünïcode')
        self.assertIn('filename="flicks-n-code.json"', exported.headers['content-disposition'])  # ASCII only

    def test_a_refused_pin_change_changes_nothing(self):
        self.client.put('/api/profiles/current', json={'pin': '1357'})
        self.client.post('/api/profiles/1/select', json={'pin': '1357'})
        refused = self.client.put('/api/profiles/current', json={'name': 'Hacked', 'pin': None, 'current_pin': '0000'})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self.client.get('/api/profiles').json()['current']['name'], 'Me')
        bad_pin = self.client.put('/api/profiles/current', json={'name': 'Renamed', 'pin': 'abc', 'current_pin': '1357'})
        self.assertEqual(bad_pin.status_code, 400)
        self.assertEqual(self.client.get('/api/profiles').json()['current']['name'], 'Me')

    def test_cross_site_requests_cannot_switch_profiles(self):
        response = self.client.post('/api/profiles/1/select', json={}, headers={'Origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)
        form = self.client.post('/api/profiles', content='name=x', headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(form.status_code, 415)


if __name__ == '__main__':
    unittest.main()
