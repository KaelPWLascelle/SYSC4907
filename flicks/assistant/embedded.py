"""A small language model that runs inside the Flicks process (llama.cpp), so no model server is needed.

Optional: `pip install 'flicks[llm]'` and a GGUF file passed with `--llm-file`. The model loads on first use
and unloads after a few idle minutes, so it costs no memory until someone asks. It is the same `Chat` as
the loopback server client (llm.LocalChat), plus `stream` for answers that should appear word by word.
Every reply is untrusted text; callers validate it. docs/adr/0019-title-chat.md.
"""
from pathlib import Path
import threading
import time

from .llm import THINKING, LLMError

IDLE_SECONDS = 5 * 60


def _runtime():
    try:
        from llama_cpp import Llama
    except ImportError:
        return None
    return Llama


class EmbeddedChat:
    """One generation at a time; the model is loaded lazily and dropped when idle."""

    def __init__(self, path, *, threads=4, gpu_layers=-1, context=2048, idle_seconds=IDLE_SECONDS,
                 runtime=_runtime):
        self.path = Path(path)
        self.model = self.path.stem
        self.name = f'built-in model ({self.model})'
        self.threads, self.gpu_layers, self.context, self.idle_seconds = threads, gpu_layers, context, idle_seconds
        self.runtime = runtime
        self.lock = threading.Lock()
        self._llm = None
        self._used = 0.0
        self._timer = None
        self.load_seconds = None

    # ---- Chat protocol ----
    def complete(self, messages, *, json_mode=False, max_tokens=300, wait=None):
        return ''.join(self.stream(messages, max_tokens=max_tokens, wait=wait, json_mode=json_mode)).strip()

    def stream(self, messages, *, max_tokens=300, wait=None, json_mode=False):
        """Yield the reply's text as it is generated. Thinking blocks are dropped."""
        if not self.lock.acquire(timeout=60 if wait is None else wait):
            raise LLMError('The built-in model is busy; try again in a moment')
        try:
            llm = self._load()
            options = {'stream': True, 'max_tokens': max_tokens, 'temperature': 0.2}
            if json_mode:
                options['response_format'] = {'type': 'json_object'}
            buffer, thinking, started = '', False, False
            for chunk in llm.create_chat_completion(messages, **options):
                delta = chunk['choices'][0]['delta'].get('content')
                if not delta:
                    continue
                buffer += delta
                # Thinking models (Qwen3) may open with <think>…</think>; hold text back until it closes.
                if not started:
                    head = buffer.lstrip()
                    if len(head) < len('<think>') and '<think>'.startswith(head):
                        continue  # could still become "<think>"
                    thinking, started = head.startswith('<think>'), True
                if thinking:
                    if '</think>' not in buffer:
                        continue
                    buffer, thinking = THINKING.sub('', buffer).lstrip(), False
                if buffer:
                    yield buffer
                buffer = ''
            if buffer and not thinking:
                yield buffer  # a reply too short to tell from "<think>", e.g. "<3"
        except LLMError:
            raise
        except Exception as exc:  # the runtime raises plain exceptions (bad file, out of memory...)
            raise LLMError(f'The built-in model failed: {exc}') from None
        finally:
            self._used = time.monotonic()
            self._schedule_unload()
            self.lock.release()

    def status(self):
        if self.runtime() is None:
            return {'available': False, 'name': self.name,
                    'message': "The built-in model needs llama-cpp-python: pip install 'flicks[llm]'"}
        if not self.path.is_file():
            return {'available': False, 'name': self.name, 'message': f'Model file not found: {self.path}'}
        return {'available': True, 'name': self.name, 'message': 'Loaded' if self._llm else 'Loads on first question'}

    # ---- loading ----
    def _load(self):
        if self._llm is None:
            Llama = self.runtime()
            if Llama is None:
                raise LLMError("The built-in model needs llama-cpp-python: pip install 'flicks[llm]'")
            if not self.path.is_file():
                raise LLMError(f'Model file not found: {self.path}')
            start = time.perf_counter()
            self._llm = Llama(model_path=str(self.path), n_ctx=self.context, n_threads=self.threads,
                              n_gpu_layers=self.gpu_layers, verbose=False)
            self.load_seconds = time.perf_counter() - start
        return self._llm

    def _schedule_unload(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.idle_seconds, self._unload_if_idle)
        self._timer.daemon = True
        self._timer.start()

    def _unload_if_idle(self):
        if not self.lock.acquire(blocking=False):
            return  # in use: the generation reschedules on its way out
        try:
            if self._llm is not None and time.monotonic() - self._used >= self.idle_seconds:
                self._llm = None  # llama.cpp frees the weights when the object is collected
        finally:
            self.lock.release()
