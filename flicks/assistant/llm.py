"""Client for a large language model running on this machine (docs/adr/0013-local-llm.md).

Speaks the OpenAI-compatible `POST /v1/chat/completions` that Ollama, llama.cpp's llama-server and LM
Studio all serve, so the runtime is the user's choice. The model only ever sees text from this device,
so it must be on this device: a non-loopback URL is refused before any request, and proxies are bypassed
so a loopback hostname cannot be relayed elsewhere. Every reply is untrusted text; callers validate it.
"""
import json
import re
import threading
import time
from typing import Protocol
from urllib import error, request
from urllib.parse import urlsplit

from ..systemone import PrivacyError, is_loopback

MAX_REPLY_BYTES = 256 * 1024
THINKING = re.compile(r'<think>.*?</think>', re.S)


class LLMError(RuntimeError):
    """The model is unavailable or answered with something unusable. Callers fall back; nothing breaks."""


class Chat(Protocol):
    name: str
    model: str

    def complete(self, messages: list[dict], *, json_mode: bool = False, max_tokens: int = 300,
                 wait: float | None = None, schema: dict | None = None) -> str: ...


class LocalChat:
    """One completion per call. Calls are serialised: a small local model runs one generation at a time."""

    def __init__(self, base_url, model, timeout=60.0):
        parts = urlsplit(base_url or '')
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            raise ValueError('LLM URL must be http(s)://host[:port], for example http://127.0.0.1:11434')
        if not is_loopback(base_url):
            raise PrivacyError('The language model must run on this machine (127.0.0.1); user text never leaves it')
        if not isinstance(model, str) or not model.strip():
            raise ValueError('Name the local model, for example qwen3.5:4b')
        self.url = base_url.rstrip('/').removesuffix('/v1') + '/v1/chat/completions'
        self.model, self.timeout = model, timeout
        self.name = f'local LLM ({model})'
        self.lock = threading.Lock()
        self._status = None  # (checked at, status)

    def complete(self, messages, *, json_mode=False, max_tokens=300, wait=None, schema=None):
        """`wait`: how long to wait for an earlier generation to finish first (default: the timeout).
        `schema` is not sent: servers differ in how they take one, and callers validate the JSON anyway."""
        body = {'model': self.model, 'messages': messages, 'temperature': 0.2, 'max_tokens': max_tokens,
                'stream': False, 'reasoning_effort': 'none'}  # thinking models: answer directly; latency matters
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        req = request.Request(self.url, json.dumps(body).encode(), {'Content-Type': 'application/json'}, method='POST')
        opener = request.build_opener(request.ProxyHandler({}))  # never via http(s)_proxy (see module docstring)
        # One generation at a time. A request that cannot start in time gives up rather than holding a server
        # thread in a queue behind abandoned ones (a closed sheet does not cancel the server's work).
        if not self.lock.acquire(timeout=self.timeout if wait is None else wait):
            raise LLMError('The local model is busy; try again in a moment')
        try:
            with opener.open(req, timeout=self.timeout) as reply:
                data = json.loads(reply.read(MAX_REPLY_BYTES))
        except error.HTTPError as exc:
            raise LLMError(f'The local model answered HTTP {exc.code}') from None
        except (error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f'The local model is unreachable: {exc}') from None
        except json.JSONDecodeError:
            raise LLMError('The local model returned invalid JSON') from None
        finally:
            self.lock.release()
        try:
            content = data['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            raise LLMError('The local model returned an unexpected response') from None
        if not isinstance(content, str):
            raise LLMError('The local model returned no text')
        return THINKING.sub('', content).strip()

    def status(self):
        """Whether the runtime answers and has the model, without generating anything. Cached for 15 s."""
        now = time.monotonic()
        if self._status and now - self._status[0] < 15:
            return self._status[1]
        self._status = (now, self._check())
        return self._status[1]

    def _check(self):
        root = self.url.removesuffix('/chat/completions') + '/models'
        try:
            with request.build_opener(request.ProxyHandler({})).open(root, timeout=2) as reply:
                models = {m.get('id') for m in json.loads(reply.read(MAX_REPLY_BYTES)).get('data', [])}
        except (error.URLError, TimeoutError, OSError, json.JSONDecodeError, AttributeError):
            return {'available': False, 'name': self.name, 'message': 'The local model server is not running'}
        if self.model not in models:
            return {'available': False, 'name': self.name, 'message': f'{self.model} is not installed in the local model server'}
        return {'available': True, 'name': self.name, 'message': 'Ready'}


def parse_json(text):
    """The first JSON object in a reply (models sometimes wrap it in prose or a code fence), or LLMError."""
    start = text.find('{')
    if start < 0:
        raise LLMError('The model did not answer with JSON')
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        raise LLMError('The model answered with malformed JSON') from None
    if not isinstance(value, dict):
        raise LLMError('The model did not answer with a JSON object')
    return value
