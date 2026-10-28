"""Corner chat check: the app's own open chat (open_chat.py) on 32 requests and 4 follow-ups, for one GGUF model.

    python -m flicks.assistant.open_chat_eval ~/.flicks/models/Qwen3.5-2B-Q4_K_M.gguf
    python -m flicks.assistant.open_chat_eval MODEL.gguf --cpu --out results.json   # no Metal or CUDA

Needs the imported catalogue (`flicks setup`) and llama-cpp-python, and runs on an empty profile, so picks
for a mood are crowd favourites. Prints each request with the plan Flicks ran, the titles shown and the
answer, then the time to answer. Answers are judged by hand: does it answer what was asked, from real titles?
docs/adr/0019-title-chat.md.
"""
import argparse
import json
from pathlib import Path
import tempfile
import time

from ..config import DEFAULT_MOVIELENS, DEFAULT_SERIES, Settings
from ..core import Session
from ..services import build_services
from .embedded import EmbeddedChat

REQUESTS = [
    'Iron Man', 'like Iron Man', 'Do we have any RDJ movies?', 'What is Flicks?',
    'Tell me what Marvel movies are about?', 'hi', 'I want a superhero movie', 'something with Tom Hanks',
    'a horror movie from the 80s, 2 hours max', 'cozy and funny', 'cozy and funny, about an hour and a half',
    'date night', 'something sad', 'I loved Inception', 'something for kids, 90 minutes',
    'no horror, something light', 'Pixar', 'anime', 'what can you do?', 'a documentary about space',
    'surprise me', 'Who is in Alien?', 'Is Toy Story OK for kids?', 'How long is The Godfather?',
    'something like Toy Story but for adults', 'Christopher Nolan films', 'Star Wars', 'a heist movie',
    'films set in Paris', 'a short comedy series', 'what should I watch after Arrival?',
    'Leonardo DiCaprio movies from the 2010s',
]
FOLLOW_UPS = [
    ['Do we have any RDJ movies?', 'which of those is the shortest?'],
    ['a heist movie', 'something more recent'],
    ['Christopher Nolan films', 'tell me about the first one'],
]


def converse(concierge, said):
    """One conversation: (request, plan, titles, answer, seconds) per viewer message."""
    messages, previous, out = [], [], []
    for text in said:
        messages.append({'role': 'user', 'text': text})
        start = time.perf_counter()
        events = list(concierge.converse({}, Session(), messages, (), previous))
        seconds = time.perf_counter() - start
        picks = [p['content'] for e in events if 'picks' in e for p in e['picks']]
        if picks:
            previous = [item['id'] for item in picks]
        answer = events[-1]['text']
        out.append({'said': text, 'understood': events[0].get('understood'), 'step': events[-1]['step'],
                    'titles': [f"{item['title']} ({item['year']})" for item in picks], 'answer': answer,
                    'seconds': round(seconds, 2)})
        messages.append({'role': 'assistant', 'text': answer})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('model', type=Path, help='A GGUF file')
    parser.add_argument('--cpu', action='store_true', help='Run on the CPU only')
    parser.add_argument('--out', type=Path, help='Also write every answer as JSON')
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as temp:
        settings = Settings(db=Path(temp)/'eval.sqlite3', catalog=DEFAULT_MOVIELENS,
                            neighbours=DEFAULT_MOVIELENS.with_name(DEFAULT_MOVIELENS.stem + '.neighbours.json'),
                            series=DEFAULT_SERIES if DEFAULT_SERIES.is_file() else None)
        chat = EmbeddedChat(args.model, gpu_layers=0 if args.cpu else -1)
        services = build_services(settings, chat=chat)
        rows = []
        for said in [[text] for text in REQUESTS] + FOLLOW_UPS:
            for row in converse(services.concierge, said):
                rows.append(row)
                print(f"[{row['seconds']:.2f} s] {row['said']} | {', '.join(row['understood'] or [])}\n"
                      f"    {'; '.join(row['titles']) or '(no titles)'}\n    {row['answer']}", flush=True)
        times = sorted(row['seconds'] for row in rows)
        summary = {'model': args.model.name, 'backend': 'cpu' if args.cpu else 'gpu', 'load_s': chat.load_seconds,
                   'median_s': times[len(times) // 2], 'max_s': times[-1],
                   'with_titles': sum(bool(row['titles']) for row in rows), 'requests': len(rows)}
        print(json.dumps(summary, indent=1))
        if args.out:
            args.out.write_text(json.dumps({'summary': summary, 'rows': rows}, indent=1))
        chat._llm = None  # free llama.cpp before exit: its Metal teardown asserts with a model still loaded


if __name__ == '__main__':
    main()
