"""Fast command/transport tests; optional audio decoding tests with voice extras."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import wave

from flicks.commands import CommandInterpreter
from flicks.core import Recommender, Session, load_catalog
from flicks.voice import MAX_AUDIO_BYTES, LocalWhisper, VoiceUnavailable
from helpers import CATALOG, app_client


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CATALOG)
        self.parser = CommandInterpreter(self.catalog)

    def test_spoken_session_request(self):
        result = self.parser.parse('Hey Flicks, something relaxing under ninety minutes, low intensity, no horror.')
        self.assertEqual(result['intent'], 'session')
        self.assertEqual(result['patch'], {'mood': 'relaxing', 'minutes': 89, 'intensity': .2, 'excluded_genres': ['horror']})

    def test_time_language(self):
        for text, expected in [('ninety minutes', 90), ('an hour', 60), ('an hour and a half', 90), ('half an hour', 30), ('one hundred and twenty minutes', 120), ('one hundred minutes', 100), ('two hours', 120), ('at most 90 minutes', 90), ('less than 90 minutes', 89)]:
            with self.subTest(text=text): self.assertEqual(self.parser.parse(text)['patch']['minutes'], expected)

    def test_feedback_and_negation(self):
        for text, value in [('I like Arrival', 1), ('Flicks, I disliked Arrival', -1), ("I didn't like Arrival", -1), ('Clear my rating for Arrival', 0)]:
            with self.subTest(text=text):
                result = self.parser.parse(text)
                self.assertEqual((result['intent'], result['id'], result['value']), ('feedback', 'm001', value))

    def test_title_normalization(self):
        self.assertEqual(self.parser.parse('Like Amelie')['id'], 'm020')
        self.assertEqual(self.parser.parse('Like WALL E')['id'], 'm005')

    def test_ambiguous_and_unknown_commands_never_invent_actions(self):
        for text in ['like it', 'like Paddington or Paddington 2', 'delete everything', 'play Arrival', 'relaxing and tense', 'not relaxing', 'not under 90 minutes', 'like Arrivall', '1 hour 30 minutes', '90.5 minutes', '-20 minutes']:
            with self.subTest(text=text): self.assertEqual(self.parser.parse(text)['intent'], 'unknown')

    def test_invalid_values(self):
        for text in ['', None, ['hello'], 'x'*501, '700 minutes', 'under 1 minute']:
            with self.subTest(text=text), self.assertRaises(ValueError): self.parser.parse(text)

    def test_discovery_and_clear_exclusions(self):
        self.assertEqual(self.parser.parse('Surprise me')['patch']['novelty'], .9)
        self.assertEqual(self.parser.parse('allow all genres')['patch']['excluded_genres'], [])
        self.assertEqual(self.parser.parse('familiar')['patch']['novelty'], .1)

    def test_genre_exclusions_hard_in_both_modes(self):
        engine = Recommender(self.catalog)
        for mode in ('baseline', 'session'):
            results = engine.recommend({}, Session(minutes=600, excluded_genres=['horror', 'animation']), mode, 100)
            self.assertTrue(results)
            self.assertTrue(all(not set(r['content']['genres']) & {'horror', 'animation'} for r in results))

    def test_exclusion_validation(self):
        for values in ('horror', [False], [''], ['a']*21):
            with self.assertRaises(ValueError): Session(excluded_genres=values)
        self.assertEqual(Session(excluded_genres=['horror','horror']).excluded_genres, ('horror',))


class CommandApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = app_client(Path(self.temp.name))
        self.client, _ = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def request(self, path, payload, content_type='application/json'):
        if content_type == 'application/json':
            response = self.client.post(path, json=payload)
        else:
            response = self.client.post(path, content=payload, headers={'Content-Type': content_type})
        return response.status_code, response.json()

    def test_preview_has_no_feedback_side_effect(self):
        code, result = self.request('/api/command/preview', {'text':'Like Arrival'})
        self.assertEqual(code, 200)
        self.assertEqual(result['feedback'], {})
        self.assertEqual(result['command']['id'], 'm001')
        code, result = self.request('/api/command/apply', {'text':'Like Arrival'})
        self.assertEqual(result['feedback'], {'m001':1})
        self.request('/api/command/apply', {'text':'Clear my rating for Arrival'})
        self.assertEqual(self.request('/api/command/preview', {'text':'Like Arrival'})[1]['feedback'], {})

    def test_session_patch_preserves_other_controls(self):
        data = {'text':'relaxing', 'session': {'minutes':60, 'novelty':.8, 'excluded_genres':['horror']}}
        preview = self.request('/api/command/preview', data)[1]
        self.assertEqual(preview['session']['mood'], 'any')
        result = self.request('/api/command/apply', data)[1]
        self.assertEqual(result['session']['mood'], 'relaxing')
        self.assertEqual(result['session']['minutes'], 60)
        self.assertEqual(result['session']['novelty'], .8)
        self.assertEqual(result['session']['excluded_genres'], ['horror'])

    def test_unsupported_commands_and_client_invented_actions_rejected(self):
        self.assertEqual(self.request('/api/command/apply', {'text':'like it'})[0], 400)
        self.assertEqual(self.request('/api/command/apply', {'text':'Like Arrival', 'id':'m002', 'value':-1})[0], 400)
        self.assertEqual(self.request('/api/command/apply', {'text':'Like Arrival', 'session':{'minutes':0}})[0], 400)

    def test_transcription_does_not_apply_rating(self):
        code, result = self.request('/api/transcribe', b'audio', 'audio/webm')
        self.assertEqual((code, result['text']), (200, 'Like Arrival'))
        self.assertEqual(self.request('/api/command/preview', {'text':'Like Arrival'})[1]['feedback'], {})

    def test_audio_transport_validation(self):
        self.assertEqual(self.request('/api/transcribe', b'bad', 'text/plain')[0], 415)
        self.assertEqual(self.request('/api/transcribe', b'x' * (5 * 1024 * 1024 + 1), 'audio/wav')[0], 413)
        self.assertEqual(self.request('/api/transcribe', b'', 'audio/wav')[0], 400)
        self.assertEqual(self.request('/api/transcribe', b'unavailable', 'audio/wav')[0], 503)


class VoiceSetupTests(unittest.TestCase):
    def test_disabled_by_default(self):
        voice = LocalWhisper()
        self.assertFalse(voice.status()['available'])
        with self.assertRaises(VoiceUnavailable): voice.transcribe(b'audio')

    def test_nonexistent_model_does_not_download(self):
        with tempfile.TemporaryDirectory() as folder:
            voice = LocalWhisper(Path(folder)/'nonexistent-model')
            self.assertFalse(voice.status()['available'])
            with self.assertRaises(VoiceUnavailable): voice.transcribe(b'audio')
            self.assertFalse((Path(folder)/'nonexistent-model').exists())

    def test_empty_and_oversized_audio(self):
        for data in (b'', b'x'*(MAX_AUDIO_BYTES+1)):
            with self.assertRaises(ValueError): LocalWhisper().transcribe(data)


@unittest.skipUnless(importlib.util.find_spec('av'), 'Optional voice dependencies are not installed')
class AudioDecodeTests(unittest.TestCase):
    def wav(self, seconds, amplitude=0):
        import struct
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(struct.pack('<h', amplitude)*int(seconds*16000))
        return output.getvalue()

    def test_invalid_audio(self):
        from flicks.voice import decode_audio
        with self.assertRaises(ValueError): decode_audio(b'not audio')

    def test_silent_short_and_long_recordings(self):
        from flicks.voice import decode_audio
        for data in (self.wav(1), self.wav(.01, 1000), self.wav(31, 1000)):
            with self.assertRaises(ValueError): decode_audio(data)

    def test_decodes_to_mono_16khz_float(self):
        from flicks.voice import decode_audio
        audio = decode_audio(self.wav(1, 1000))
        self.assertEqual(audio.shape, (16000,))
        self.assertAlmostEqual(float(audio[0]), 1000/32768)

if __name__ == '__main__': unittest.main()
