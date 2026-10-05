from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from flicks import db as db_module
from flicks.db import SCHEMA_VERSION, Database
from flicks.repositories import COMPLETE_FRACTION, RESUME_MIN_SECONDS, RatingsRepository, WatchHistoryRepository


def execute(path, *statements):
    """Run statements in one committed transaction and close the connection.

    `with sqlite3.connect(...)` only commits; it leaves the file open, and Windows then refuses to
    delete the temporary directory.
    """
    with closing(sqlite3.connect(path)) as connection, connection:
        return [connection.execute(statement).fetchall() for statement in statements]


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'nested'/'flicks.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def tables(self):
        [rows] = execute(self.path, "SELECT name FROM sqlite_master WHERE type = 'table'")
        return {row[0] for row in rows}

    def test_fresh_database_gets_the_whole_schema(self):
        database = Database(self.path)
        self.assertEqual(database.version(), SCHEMA_VERSION)
        self.assertEqual(self.tables(), {'feedback', 'watch_history'})

    def test_a_database_from_before_migrations_keeps_its_ratings(self):
        # Exactly the schema the app created before migrations existed (user_version 0).
        self.path.parent.mkdir(parents=True)
        execute(self.path,
                'CREATE TABLE IF NOT EXISTS feedback (content_id TEXT PRIMARY KEY, value INTEGER NOT NULL '
                'CHECK(value IN (-1,1)), updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)',
                "INSERT INTO feedback (content_id, value) VALUES ('m001', 1), ('m008', -1)")
        database = Database(self.path)
        self.assertEqual(database.version(), SCHEMA_VERSION)
        self.assertEqual(RatingsRepository(database).all(), {'m001': 1, 'm008': -1})

    def test_reopening_is_a_no_op(self):
        Database(self.path)
        RatingsRepository(Database(self.path)).set('m001', 1)
        self.assertEqual(RatingsRepository(Database(self.path)).all(), {'m001': 1})

    def test_refuses_a_database_from_a_newer_version(self):
        Database(self.path)
        execute(self.path, f'PRAGMA user_version = {SCHEMA_VERSION + 1}')
        with self.assertRaisesRegex(RuntimeError, 'newer Flicks'):
            Database(self.path)

    def test_a_failing_migration_rolls_back_completely(self):
        Database(self.path)
        broken = (*db_module.MIGRATIONS, 'CREATE TABLE extra (id INTEGER); INSERT INTO missing_table VALUES (1);')
        with mock.patch.object(db_module, 'MIGRATIONS', broken), mock.patch.object(db_module, 'SCHEMA_VERSION', len(broken)), \
                self.assertRaises(sqlite3.OperationalError):
            Database(self.path)
        self.assertNotIn('extra', self.tables())
        self.assertEqual(Database(self.path).version(), SCHEMA_VERSION)


class WatchHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.history = WatchHistoryRepository(Database(Path(self.temp.name)/'flicks.sqlite3'))

    def tearDown(self):
        self.temp.cleanup()

    def test_progress_rules(self):
        early = self.history.save('m001', RESUME_MIN_SECONDS - 1, 6000)
        self.assertFalse(early.resumable)  # an accidental start is not "continue watching"
        middle = self.history.save('m001', 1200, 6000)
        self.assertTrue(middle.resumable)
        self.assertFalse(middle.completed)
        done = self.history.save('m001', 6000 * COMPLETE_FRACTION, 6000)
        self.assertTrue(done.completed)
        self.assertFalse(done.resumable)
        self.assertEqual(self.history.save('m001', 9999, 6000).position_seconds, 6000)  # clamped to the runtime

    def test_most_recent_first_and_clear(self):
        self.history.save('m001', 100, 6000)
        self.history.save('m002', 100, 6000)
        self.history.save('m001', 200, 6000)
        self.assertEqual([p.content_id for p in self.history.recent()], ['m001', 'm002'])
        self.history.clear('m001')
        self.assertIsNone(self.history.get('m001'))
        self.assertEqual([p.content_id for p in self.history.recent()], ['m002'])

    def test_rejects_impossible_values(self):
        for position, duration in ((-1, 100), (10, 0), (10, -5), (float('nan'), 100), (10, float('inf')), (True, 100), ('5', 100)):
            with self.subTest(position=position, duration=duration), self.assertRaises(ValueError):
                self.history.save('m001', position, duration)


if __name__ == '__main__':
    unittest.main()
