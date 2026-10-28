"""Shared test helpers: build the real app on temporary storage and call it like a page on 127.0.0.1."""
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from flicks.api.app import create_app
from flicks.assistant.voice import VoiceUnavailable
from flicks.config import DEFAULT_CATALOG, Settings
from flicks.services import build_services

PACKAGE = DEFAULT_CATALOG.parents[1]
CATALOG = DEFAULT_CATALOG


class FakeSpeech:
    def status(self):
        return {'available': True, 'message': 'test speech'}

    def transcribe(self, data):
        if data == b'unavailable':
            raise VoiceUnavailable('Unavailable for this test')
        return {'text': 'Like Arrival', 'engine': 'test'}


def write_frontend(directory: Path):
    """A stand-in for the Vite build, so backend tests do not depend on Node."""
    (directory/'assets').mkdir(parents=True, exist_ok=True)
    (directory/'index.html').write_text('<!doctype html><title>Flicks</title><div id="root"></div>', encoding='utf-8')
    (directory/'couch.html').write_text('<!doctype html><title>Flicks couch</title><div id="root"></div>', encoding='utf-8')
    (directory/'assets'/'app-1234.js').write_text('export {}', encoding='utf-8')
    (directory/'manifest.webmanifest').write_text('{"name": "Flicks"}', encoding='utf-8')
    return directory


class FakeChat:
    """A scripted local language model: returns `replies` in order and records every request."""
    name, model = 'fake LLM', 'fake-model'

    def __init__(self, *replies, error=None):
        self.replies, self.error, self.requests = list(replies), error, []

    def complete(self, messages, *, json_mode=False, max_tokens=300, wait=None, schema=None):
        self.requests.append({'messages': list(messages), 'json_mode': json_mode, 'wait': wait, 'schema': schema})
        if self.error:
            raise self.error
        if not self.replies:
            from flicks.assistant.llm import LLMError
            raise LLMError('no scripted reply left')
        return self.replies.pop(0)


@contextmanager
def app_client(tmp: Path, *, speech=None, system_one=None, chat=None, **overrides):
    """(TestClient, Services) for an app whose data lives under tmp."""
    settings = Settings(db=tmp/'flicks.sqlite3', static_dir=write_frontend(tmp/'static'), **overrides)
    services = build_services(settings, speech=speech or FakeSpeech(), system_one=system_one, chat=chat)
    try:
        with TestClient(create_app(settings, services), base_url=f'http://127.0.0.1:{settings.port}') as client:
            yield client, services
    finally:
        if services.couch:
            services.couch.stop()
