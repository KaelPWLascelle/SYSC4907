"""Command line entry point: `flicks` or `python -m flicks`; `flicks setup` downloads the catalogues (flicks/setup.py)."""
import argparse
import importlib.util
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from .api.app import create_app
from .assistant.voice import LocalWhisper
from .config import DEFAULT_CATALOG, DEFAULT_DB, DEFAULT_MODEL, DEFAULT_POSTERS, DEFAULT_SERIES, Settings, default_films
from .services import build_services
from .systemone import DecisionClient, HttpBackend, LexicalBackend

VITE_DEV_ORIGINS = ('http://localhost:5173', 'http://127.0.0.1:5173')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog='flicks', description='Flicks: local-first movie recommendations and playback',
        epilog='First time? Run `flicks setup` to download about 9,000 films, TV series and posters; '
               '`flicks setup --check` shows what is installed.')
    parser.add_argument('--catalog', type=Path, help='Film catalogue (default: the one `flicks setup` imported, else the 36-film demo)')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB, help=f'Ratings and watch history (default {DEFAULT_DB})')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--media', type=Path, action='append', default=[], metavar='DIR',
                        help='Folder of video files to play; repeatable. Name files "Title (Year).mp4" or by content ID')
    parser.add_argument('--posters', type=Path, default=DEFAULT_POSTERS, help=f'Poster cache from flicks setup (default {DEFAULT_POSTERS})')
    parser.add_argument('--voice-model', type=Path, help='Local faster-whisper model directory; no runtime downloads')
    parser.add_argument('--series', type=Path, help=f'TV series from python -m flicks.datasets.tvmaze (default: {DEFAULT_SERIES} when present)')
    parser.add_argument('--no-series', action='store_true', help='Films only, even when a series catalogue is present')
    parser.add_argument('--archive', type=Path, help='Internet Archive matches to stream (default: <catalog>.archive.json when present)')
    parser.add_argument('--trailers', type=Path, help='Trailer index for Discover (default: <catalog>.trailers.json when present)')
    parser.add_argument('--neighbours', type=Path, help='Collaborative-filtering neighbours (default: <catalog>.neighbours.json when present)')
    parser.add_argument('--tags', type=Path, help='System One tag file from python -m flicks.tagging (soft mood/intensity)')
    parser.add_argument('--system-one-url', help='Local System One server for free-text commands, e.g. http://127.0.0.1:8000 (laya-serve), or "lexical" for the offline stand-in')
    parser.add_argument('--llm-url', help='Optional, experimental: a local language model server (OpenAI-compatible), e.g. '
                        'http://127.0.0.1:11434 for Ollama. Needs several GB of free memory; Flicks does not need it')
    parser.add_argument('--llm-file', type=Path, metavar='GGUF',
                        help='A small GGUF model run inside Flicks for the chats (default: the one `flicks setup --model` '
                             'downloads, when it and llama-cpp-python are installed)')
    parser.add_argument('--no-llm', action='store_true', help='Do not load a language model, even if one is installed')
    parser.add_argument('--llm-cpu', action='store_true', help='Run the --llm-file model on the CPU only')
    parser.add_argument('--llm-model', default='qwen3.5:2b', help='Model name in that server (default qwen3.5:2b)')
    parser.add_argument('--no-ask-student', action='store_true', help='Turn off the distilled Ask student (rules only)')
    parser.add_argument('--couch', action=argparse.BooleanOptionalAction, default=True,
                        help='Offer couch sessions: phones on your Wi-Fi join by QR code to vote and use a remote. '
                             'Nothing listens on the network until you start one (default: on; --no-couch hides it)')
    parser.add_argument('--couch-host', help='Home-network address guests connect to (default: detected)')
    parser.add_argument('--couch-port', type=int, default=8770, help='Port for the guest server while a couch session runs')
    parser.add_argument('--dev', action='store_true', help='Also accept API calls from the Vite dev server (npm run dev)')
    parser.add_argument('--no-browser', action='store_true', help='Do not open the browser when Flicks starts')
    args = parser.parse_args(argv)
    args.catalog = args.catalog or default_films()
    if args.llm_file is None and not (args.no_llm or args.llm_url) and DEFAULT_MODEL.is_file() \
            and importlib.util.find_spec('llama_cpp') is not None:
        args.llm_file = DEFAULT_MODEL  # installed by `flicks setup --model`
    if args.no_llm:
        args.llm_file = args.llm_url = None
    return args


def _sidecar(catalog, suffix='.neighbours.json'):
    """A file built next to an imported catalogue (neighbours, Archive matches), if it exists."""
    path = catalog.with_suffix(suffix)
    return path if path.is_file() else None


def _port_free(port):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def _open_when_ready(url, port, seconds=20):
    """Open the browser once the server accepts connections (it may take a few seconds to load the catalogue)."""
    def wait():
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                probe.settimeout(0.5)
                if probe.connect_ex(('127.0.0.1', port)) == 0:
                    webbrowser.open(url)
                    return
            time.sleep(0.3)
    threading.Thread(target=wait, daemon=True).start()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ['setup']:
        from . import setup
        return setup.main(argv[1:])
    args = parse_args(argv)
    if not _port_free(args.port):
        print(f'Port {args.port} is in use: Flicks may already be running at http://127.0.0.1:{args.port}. '
              f'Open it there, or start another copy with --port {args.port + 1}.', file=sys.stderr)
        return 1
    settings = Settings(db=args.db, catalog=args.catalog, port=args.port, poster_dir=args.posters,
                        media_dirs=tuple(args.media), tags=args.tags, neighbours=args.neighbours or _sidecar(args.catalog),
                        archive=args.archive or _sidecar(args.catalog, '.archive.json'),
                        trailers=args.trailers or _sidecar(args.catalog, '.trailers.json'),
                        series=None if args.no_series else args.series or (DEFAULT_SERIES if DEFAULT_SERIES.is_file() else None),
                        couch=args.couch, couch_host=args.couch_host,
                        couch_port=args.couch_port, llm_url=args.llm_url, llm_model=args.llm_model,
                        llm_file=args.llm_file, llm_gpu=not args.llm_cpu,
                        ask_student=None if args.no_ask_student else Settings.ask_student,
                        extra_origins=VITE_DEV_ORIGINS if args.dev else ())
    if args.system_one_url == 'lexical':  # offline demo of the fallback path; not a model
        system_one = DecisionClient(LexicalBackend())
    else:
        system_one = DecisionClient(HttpBackend(args.system_one_url, timeout=5)) if args.system_one_url else None
    services = build_services(settings, speech=LocalWhisper(args.voice_model), system_one=system_one)
    if services.media.unmatched:
        print(f'Media: {len(services.media.unmatched)} file(s) did not match a catalogue title, e.g. {services.media.unmatched[0].name}')
    mode = ' + '.join(['content', *(['collaborative'] if services.collaborative else []),
                        *(['popularity prior'] if services.popularity_prior else [])])
    streamed = f' · films to stream: {len(services.streams)}' if len(services.streams) else ''
    streamed += f' · series: {services.series}' if services.series else ''
    llm = f' · {services.chat.name}' if services.chat else ''
    url = f'http://127.0.0.1:{settings.port}'
    print(f'Flicks: {url} · ratings: {settings.db} · {mode} recommendations · '
          f'playable titles: {len(services.media.files)}{streamed}{llm}', flush=True)
    if args.catalog == DEFAULT_CATALOG:
        print('Using the 36-film demo catalogue. Run `flicks setup` for about 9,000 films, TV series and posters.')
    print('Press Ctrl+C to stop.', flush=True)
    if not (args.no_browser or args.dev):
        _open_when_ready(url, settings.port)
    try:
        uvicorn.run(create_app(settings, services), host='127.0.0.1', port=settings.port, log_level='warning')
    finally:
        if services.couch:
            services.couch.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
