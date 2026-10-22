import contextlib
import hashlib
import io
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from flicks import __main__ as cli
from flicks import config, setup


class FakeReply(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DefaultsTests(unittest.TestCase):
    def test_the_imported_catalogue_is_used_when_present_else_the_demo(self):
        with tempfile.TemporaryDirectory() as temp:
            imported = Path(temp)/'movielens-small.json'
            with mock.patch.object(config, 'DEFAULT_MOVIELENS', imported):
                self.assertEqual(cli.parse_args([]).catalog, config.DEFAULT_CATALOG)
                imported.write_text('[]')
                self.assertEqual(cli.parse_args([]).catalog, imported)
                self.assertEqual(cli.parse_args(['--catalog', 'x.json']).catalog, Path('x.json'))

    def test_the_downloaded_model_is_used_only_with_its_runtime_and_not_with_no_llm(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp)/'model.gguf'
            model.write_bytes(b'x')
            with mock.patch.object(cli, 'DEFAULT_MODEL', model):
                with mock.patch.object(cli.importlib.util, 'find_spec', return_value=None):
                    self.assertIsNone(cli.parse_args([]).llm_file)
                with mock.patch.object(cli.importlib.util, 'find_spec', return_value=object()):
                    self.assertEqual(cli.parse_args([]).llm_file, model)
                    self.assertIsNone(cli.parse_args(['--no-llm']).llm_file)
                    self.assertIsNone(cli.parse_args(['--llm-url', 'http://127.0.0.1:11434']).llm_file)

    def test_a_port_in_use_is_reported_instead_of_a_traceback(self):
        with socket.socket() as busy:
            busy.bind(('127.0.0.1', 0))
            busy.listen()
            port = busy.getsockname()[1]
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(cli.main(['--port', str(port)]), 1)
            self.assertIn('already be running', err.getvalue())


class SetupTests(unittest.TestCase):
    def test_check_lists_what_is_installed(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(['setup', '--check']), 0)
        for name in ('Interface', 'Films', 'TV series', 'Posters', 'Language model'):
            self.assertIn(name, out.getvalue())

    def test_a_failed_step_is_reported_and_the_rest_still_run(self):
        ran = []

        def ok():
            ran.append('posters')
            return 'fine'

        def broken():
            ran.append('series')
            raise OSError('no connection')

        steps = [('series', 'Series', broken, False), ('posters', 'Posters', ok, False), ('model', 'Model', ok, False)]
        out = io.StringIO()
        with mock.patch.object(setup, 'STEPS', steps), contextlib.redirect_stdout(out):
            self.assertEqual(setup.main([]), 1)
        self.assertEqual(ran, ['series', 'posters'])  # the model is opt-in
        self.assertIn('failed: no connection', out.getvalue())
        self.assertIn('did not finish: series', out.getvalue())

    def test_the_model_is_kept_only_when_its_checksum_matches(self):
        data = b'weights' * 1000
        good = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'models'/'model.gguf'
            with mock.patch.object(setup.request, 'urlopen', return_value=FakeReply(data)):
                with self.assertRaises(ValueError):
                    setup.download_model(path, 'https://example.org/m.gguf', 'bad', len(data), out=io.StringIO())
                self.assertFalse(path.exists())
                self.assertFalse(path.with_name('model.gguf.part').exists())
            with mock.patch.object(setup.request, 'urlopen', return_value=FakeReply(data)):
                setup.download_model(path, 'https://example.org/m.gguf', good, len(data), out=io.StringIO())
            self.assertEqual(path.read_bytes(), data)




class RetryTests(unittest.TestCase):
    def test_a_temporary_failure_is_retried_and_a_permanent_one_is_not(self):
        from urllib import error

        from flicks import net
        flaky = [error.URLError('timed out'), FakeReply(b'ok')]
        with mock.patch.object(net.request, 'urlopen', side_effect=flaky) as urlopen:
            self.assertEqual(net.get('https://example.org', 10, waits=(0,)), b'ok')
        self.assertEqual(urlopen.call_count, 2)
        missing = error.HTTPError('https://example.org', 404, 'Not Found', {}, None)
        with mock.patch.object(net.request, 'urlopen', side_effect=[missing, FakeReply(b'ok')]) as urlopen, \
                self.assertRaises(error.HTTPError):
            net.get('https://example.org', 10, waits=(0,))
        self.assertEqual(urlopen.call_count, 1)


if __name__ == '__main__':
    unittest.main()
