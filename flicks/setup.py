"""`flicks setup`: everything Flicks can download, in one command (docs/adr/0020-packaging.md).

    flicks setup               # films, public-domain streams, trailers, TV series and posters
    flicks setup --no-series   # skip TV series, the slowest step (about half an hour the first time)
    flicks setup --model       # also the small language model for the chats (about 1 GB)
    flicks setup --check       # show what is installed, without downloading anything

Each step is one of the import commands the README documents, run in order. They cache what they
download under ~/.flicks, so setup can be stopped and run again: finished work is quick the second time.
Only public data is downloaded, and nothing about the user is sent. A step that fails (no connection,
a service down) is reported and the others still run.
"""
import argparse
import hashlib
import importlib.util
import json
import sys
import time
from urllib import request

from . import net
from .config import DEFAULT_CATALOG, DEFAULT_MODEL, DEFAULT_MOVIELENS, DEFAULT_POSTERS, DEFAULT_SERIES, DEFAULT_STATIC

# Qwen2.5 1.5B Instruct, 4-bit (Apache 2.0), pinned to one revision and checked by its SHA-256, so the file
# Flicks runs is exactly the one the team evaluated (docs/adr/0019-title-chat.md).
MODEL_URL = ('https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/'
             '9eadc66189c7641e1ddd226b8267a9119b2ce2d4/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf')
MODEL_SHA256 = '1adf0b11065d8ad2e8123ea110d1ec956dab4ab038eab665614adba04b6c3370'
MODEL_BYTES = 986_048_768
RUNTIME_HINT = ("The chats also need llama.cpp's Python package: run `pipx inject flicks llama-cpp-python` if "
                "you installed Flicks with pipx, or `pip install \"flicks[llm]\"` otherwise.")


def _films():
    from .datasets.movielens import import_movielens
    result = import_movielens()
    return f"{result['titles']:,} films" + ('' if result.get('neighbours') else ' (no collaborative filtering: NumPy missing)')


def _streams():
    from .datasets.archive import import_archive
    return f"{import_archive(DEFAULT_MOVIELENS)['films']} public-domain films to stream"


def _trailers():
    from .datasets.trailers import import_trailers
    result = import_trailers(DEFAULT_MOVIELENS)
    return f"{result['kept']:,} films with a trailer"


def _series():
    from .datasets import tvmaze
    tvmaze.main([])
    return f'{_count(DEFAULT_SERIES):,} TV series'


def _posters():
    from . import posters
    posters.main([])
    return f'{_posters_cached():,} posters'


def _model():
    if not DEFAULT_MODEL.is_file() or _sha256(DEFAULT_MODEL) != MODEL_SHA256:
        download_model()
    return 'language model ready' if runtime_installed() else 'language model downloaded (runtime missing, see below)'


STEPS = [  # (name, what it adds, function, needs the films first)
    ('films', 'MovieLens catalogue (about 9,000 films), descriptions and collaborative filtering', _films, False),
    ('streams', 'Public-domain films to stream from the Internet Archive', _streams, True),
    ('trailers', 'Trailer IDs for Discover (videos are never downloaded)', _trailers, True),
    ('series', 'About 1,000 TV series from TVmaze (slow the first time: about half an hour)', _series, False),
    ('posters', 'Posters and covers for the most popular titles', _posters, False),
    ('model', 'The small language model for the chats (about 1 GB)', _model, False),
]


def runtime_installed():
    return importlib.util.find_spec('llama_cpp') is not None


def download_model(path=DEFAULT_MODEL, url=MODEL_URL, sha256=MODEL_SHA256, size=MODEL_BYTES, out=None):
    """Download to `<path>.part`, resuming an interrupted download, and keep it only if its SHA-256 matches."""
    out = out or sys.stdout
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + '.part')
    have = part.stat().st_size if part.is_file() else 0
    headers = {'User-Agent': net.USER_AGENT, **({'Range': f'bytes={have}-'} if have else {})}
    with request.urlopen(request.Request(url, headers=headers), timeout=60, context=net.ssl_context()) as reply:
        if have and reply.status != 206:
            have = 0  # the server ignored the range: start again
        with part.open('ab' if have else 'wb') as file:
            done, shown = have, 0.0
            while chunk := reply.read(1 << 20):
                file.write(chunk)
                done += len(chunk)
                if time.monotonic() - shown > 0.5:
                    print(f'\r  {done / 1e6:,.0f} of {size / 1e6:,.0f} MB', end='', file=out, flush=True)
                    shown = time.monotonic()
    print(file=out)
    if _sha256(part) != sha256:
        part.unlink()
        raise ValueError('the downloaded model did not match its checksum, so it was deleted; run setup again')
    part.replace(path)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _count(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 0
    if isinstance(data, dict):  # an index: the films or trailers it lists
        data = data.get('films', data.get('trailers', {}))
    return len(data)


def _posters_cached():
    if not DEFAULT_POSTERS.is_dir():
        return 0
    return sum(1 for path in DEFAULT_POSTERS.iterdir() if path.suffix in ('.jpg', '.png', '.webp'))


def status():
    """[(what, state)] for `flicks setup --check` and the end of a setup."""
    films = DEFAULT_MOVIELENS.is_file()
    sidecar = DEFAULT_MOVIELENS.with_suffix
    rows = [
        ('Interface', 'ready' if (DEFAULT_STATIC/'index.html').is_file() else 'not built (see the README)'),
        ('Films', f'{_count(DEFAULT_MOVIELENS):,} from MovieLens' if films
         else f'{_count(DEFAULT_CATALOG)} demo films only (run flicks setup)'),
        ('Collaborative filtering', 'ready' if sidecar('.neighbours.json').is_file() else 'missing'),
        ('Streams', f"{_count(sidecar('.archive.json')):,} public-domain films" if sidecar('.archive.json').is_file() else 'missing'),
        ('Trailers', f"{_count(sidecar('.trailers.json')):,} films" if sidecar('.trailers.json').is_file() else 'missing'),
        ('TV series', f'{_count(DEFAULT_SERIES):,}' if DEFAULT_SERIES.is_file() else 'missing'),
        ('Posters', f'{_posters_cached():,}' if _posters_cached() else 'missing (title cards are drawn instead)'),
        ('Language model', ('ready' if runtime_installed() else 'downloaded; runtime not installed')
         if DEFAULT_MODEL.is_file() else 'not installed (optional: flicks setup --model)'),
    ]
    return rows


def print_status(out=None):
    out = out or sys.stdout
    width = max(len(name) for name, _ in status())
    for name, state in status():
        print(f'  {name.ljust(width)}  {state}', file=out)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='flicks setup', description='Download the catalogues, posters and, optionally, '
                                     'the language model Flicks uses. Safe to stop and run again.')
    parser.add_argument('--model', action='store_true', help='Also download the small language model (about 1 GB)')
    parser.add_argument('--no-series', action='store_true', help='Skip TV series (the slowest step)')
    parser.add_argument('--no-posters', action='store_true', help='Skip posters (Flicks draws title cards instead)')
    parser.add_argument('--only', choices=[name for name, *_ in STEPS], action='append',
                        help='Run only this step (repeatable)')
    parser.add_argument('--check', action='store_true', help='Show what is installed and exit')
    args = parser.parse_args(argv)
    if args.check:
        print_status()
        return 0
    skip = {name for name, wanted in (('series', not args.no_series), ('posters', not args.no_posters),
                                      ('model', args.model)) if not wanted}
    steps = [step for step in STEPS if (step[0] in args.only if args.only else step[0] not in skip)]
    print('Flicks setup downloads public data only; nothing about you is sent. It is safe to stop and run again.')
    failed = []
    for index, (name, what, run, needs_films) in enumerate(steps, 1):
        print(f'\n[{index}/{len(steps)}] {what}', flush=True)
        if needs_films and not DEFAULT_MOVIELENS.is_file():
            print('  skipped: the film catalogue is not installed yet')
            failed.append(name)
            continue
        try:
            print(f'  done: {run()}', flush=True)
        except Exception as error:  # a network failure or a service change: report it, keep going
            print(f'  failed: {error}', flush=True)
            failed.append(name)
    print('\nFlicks now has:')
    print_status()
    if 'model' in [name for name, *_ in steps] and DEFAULT_MODEL.is_file() and not runtime_installed():
        print('\n' + RUNTIME_HINT)
    if failed:
        print(f"\nThese steps did not finish: {', '.join(failed)}. Run `flicks setup` again to retry them.")
        return 1
    print('\nStart Flicks with: flicks')
    return 0


if __name__ == '__main__':
    sys.exit(main())
