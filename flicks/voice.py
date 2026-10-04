"""Optional local Whisper transcription, with bounded in-memory audio decoding."""
import importlib.util
import io
from pathlib import Path
import threading
from time import perf_counter

MAX_AUDIO_BYTES = 5 * 1024 * 1024
MAX_AUDIO_SECONDS = 30
AUDIO_TYPES = {'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/x-wav',
               'audio/mpeg', 'audio/aiff', 'audio/x-aiff', 'audio/flac', 'application/octet-stream'}


class VoiceUnavailable(RuntimeError):
    pass


class VoiceBusy(RuntimeError):
    pass


def decode_audio(data):
    """Decode incrementally; even a compressed long recording cannot grow unbounded."""
    import av
    import numpy as np
    chunks, samples = [], 0
    try:
        with av.open(io.BytesIO(data), metadata_errors='ignore') as container:
            if not container.streams.audio:
                raise ValueError('The file has no audio stream')
            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    samples += converted.samples
                    if samples > MAX_AUDIO_SECONDS*16000:
                        raise ValueError('Recordings must be 30 seconds or shorter')
                    chunks.append(converted.to_ndarray().flatten())
            for converted in resampler.resample(None):
                samples += converted.samples
                if samples > MAX_AUDIO_SECONDS*16000:
                    raise ValueError('Recordings must be 30 seconds or shorter')
                chunks.append(converted.to_ndarray().flatten())
    except av.error.FFmpegError as error:
        raise ValueError('Cannot decode this audio file; try WAV, WebM, MP3, or M4A') from error
    if samples < 1600:
        raise ValueError('Recording is too short; speak for at least a moment')
    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    if not np.isfinite(audio).all() or np.sqrt(np.mean(audio*audio)) < .001:
        raise ValueError('No audible speech detected; check your microphone and try again')
    return audio


class LocalWhisper:
    """Loads only an explicitly configured local model directory, once per process."""
    def __init__(self, model_path=None):
        self.path = Path(model_path).resolve() if model_path else None
        self._model = None
        self._lock = threading.Lock()

    def status(self):
        reason = None
        if not self.path:
            reason = 'Voice is not configured. See docs/voice.md; typed commands work now.'
        elif not all((self.path/name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')):
            reason = 'The local Whisper model is missing or incomplete. Run the setup in docs/voice.md.'
        elif importlib.util.find_spec('faster_whisper') is None:
            reason = 'Install requirements-voice.txt in your Python environment to enable voice.'
        return {'available': reason is None, 'message': reason or 'Local Whisper ready · English · up to 30 seconds',
                'engine': 'faster-whisper', 'model': self.path.name if self.path else None,
                'loaded': self._model is not None, 'max_seconds': MAX_AUDIO_SECONDS, 'max_bytes': MAX_AUDIO_BYTES}

    def transcribe(self, data):
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_AUDIO_BYTES:
            raise ValueError('Audio must contain 1 byte to 5 MiB')
        state = self.status()
        if not state['available']:
            raise VoiceUnavailable(state['message'])
        if not self._lock.acquire(blocking=False):
            raise VoiceBusy('Flicks is already transcribing. Please retry when it finishes.')
        try:
            start = perf_counter()
            try:
                audio = decode_audio(data)
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise VoiceUnavailable('Voice dependencies are incomplete. Reinstall requirements-voice.txt.') from error
            if self._model is None:
                try:
                    self._model = WhisperModel(str(self.path), device='cpu', compute_type='int8',
                                               cpu_threads=4, local_files_only=True)
                except Exception as error:
                    raise VoiceUnavailable('Could not load the local speech model. Check the installation and model files.') from error
            try:
                segments, _ = self._model.transcribe(audio, language='en', beam_size=3,
                                                     vad_filter=True, condition_on_previous_text=False,
                                                     temperature=0, max_new_tokens=160)
                segments = [s for s in segments if s.no_speech_prob < .6]
            except Exception as error:
                raise VoiceUnavailable('Local transcription failed. Try again or use a typed command.') from error
            text = ' '.join(s.text.strip() for s in segments).strip()
            if not text:
                raise ValueError('No speech recognized; try speaking clearly or type your command')
            if len(text) > 500:
                raise ValueError('That command is too long. Try one short request.')
            return {'text': text, 'seconds': round(len(audio)/16000, 2),
                    'processing_ms': round((perf_counter()-start)*1000), 'engine': 'faster-whisper',
                    'note': 'Check the transcript before applying. Speech recognition can make mistakes.'}
        finally:
            self._lock.release()
