"""Command line entry point: `flicks` or `python -m flicks`."""
import argparse
from pathlib import Path

import uvicorn

from .api.app import create_app
from .config import DEFAULT_CATALOG, DEFAULT_DB, DEFAULT_PODCAST_DOWNLOADS, DEFAULT_PODCASTS, DEFAULT_POSTERS, Settings
from .services import build_services
from .systemone import DecisionClient, HttpBackend, LexicalBackend
from .voice import LocalWhisper

VITE_DEV_ORIGINS = ('http://localhost:5173', 'http://127.0.0.1:5173')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog='flicks', description='Flicks: local-first movie recommendations and playback')
    parser.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB, help=f'Ratings and watch history (default {DEFAULT_DB})')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--media', type=Path, action='append', default=[], metavar='DIR',
                        help='Folder of video files to play; repeatable. Name files "Title (Year).mp4" or by content ID')
    parser.add_argument('--posters', type=Path, default=DEFAULT_POSTERS, help=f'Local poster cache from python -m flicks.posters (default {DEFAULT_POSTERS})')
    parser.add_argument('--voice-model', type=Path, help='Local faster-whisper model directory; no runtime downloads')
    parser.add_argument('--podcasts', type=Path, help=f'Podcast catalogue (default: {DEFAULT_PODCASTS} when present)')
    parser.add_argument('--podcast-downloads', type=Path, default=DEFAULT_PODCAST_DOWNLOADS,
                        help=f'Where downloaded episodes are kept (default {DEFAULT_PODCAST_DOWNLOADS})')
    parser.add_argument('--archive', type=Path, help='Internet Archive matches to stream (default: <catalog>.archive.json when present)')
    parser.add_argument('--neighbours', type=Path, help='Collaborative-filtering neighbours (default: <catalog>.neighbours.json when present)')
    parser.add_argument('--tags', type=Path, help='System One tag file from python -m flicks.tagging (soft mood/intensity)')
    parser.add_argument('--system-one-url', help='Local System One server for free-text commands, e.g. http://127.0.0.1:8000 (laya-serve), or "lexical" for the offline stand-in')
    parser.add_argument('--couch', action='store_true', help='Allow couch sessions: phones on your Wi-Fi join by QR code to vote and use a remote')
    parser.add_argument('--couch-host', help='Home-network address guests connect to (default: detected)')
    parser.add_argument('--couch-port', type=int, default=8770, help='Port for the guest server while a couch session runs')
    parser.add_argument('--dev', action='store_true', help='Also accept API calls from the Vite dev server (npm run dev)')
    return parser.parse_args(argv)


def _sidecar(catalog, suffix='.neighbours.json'):
    """A file built next to an imported catalogue (neighbours, Archive matches), if it exists."""
    path = catalog.with_suffix(suffix)
    return path if path.is_file() else None


def main(argv=None):
    args = parse_args(argv)
    settings = Settings(db=args.db, catalog=args.catalog, port=args.port, poster_dir=args.posters,
                        media_dirs=tuple(args.media), tags=args.tags, neighbours=args.neighbours or _sidecar(args.catalog),
                        archive=args.archive or _sidecar(args.catalog, '.archive.json'),
                        podcasts=args.podcasts or (DEFAULT_PODCASTS if DEFAULT_PODCASTS.is_file() else None),
                        podcast_downloads=args.podcast_downloads,
                        couch=args.couch, couch_host=args.couch_host,
                        couch_port=args.couch_port, extra_origins=VITE_DEV_ORIGINS if args.dev else ())
    if args.system_one_url == 'lexical':  # offline demo of the fallback path; not a model
        system_one = DecisionClient(LexicalBackend())
    else:
        system_one = DecisionClient(HttpBackend(args.system_one_url, timeout=5)) if args.system_one_url else None
    services = build_services(settings, speech=LocalWhisper(args.voice_model), system_one=system_one)
    if services.media.unmatched:
        print(f'Media: {len(services.media.unmatched)} file(s) did not match a catalogue title, e.g. {services.media.unmatched[0].name}')
    mode = ' + '.join(['content', *(['collaborative'] if services.collaborative else []),
                        *(['popularity prior'] if services.popularity_prior else [])])
    episodes = f' · podcast episodes: {len(services.podcasts.index)}' if services.podcasts else ''
    streamed = len(services.streams) - (len(services.podcasts.index) if services.podcasts else 0)
    episodes += f' · films to stream: {streamed}' if streamed else ''
    print(f'Flicks: http://127.0.0.1:{settings.port} · ratings: {settings.db} · {mode} recommendations · '
          f'playable titles: {len(services.media.files)}{episodes}', flush=True)
    try:
        uvicorn.run(create_app(settings, services), host='127.0.0.1', port=settings.port, log_level='warning')
    finally:
        if services.couch:
            services.couch.stop()


if __name__ == '__main__':
    main()
