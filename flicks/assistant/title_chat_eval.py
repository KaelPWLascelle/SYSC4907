"""Title chat check: the app's own prompt and answer check on 3 titles x 8 questions, for one GGUF model.

    python -m flicks.assistant.title_chat_eval ~/.flicks/models/Qwen3.5-2B-Q4_K_M.gguf
    python -m flicks.assistant.title_chat_eval MODEL.gguf --cpu --out results.json   # no Metal or CUDA

Needs the imported catalogue (`flicks setup`) and llama-cpp-python. Prints every answer with its timing, then
load time, added memory, time to first words and to the full answer, and how many answers the check withdrew.
Answers are scored by hand (right, partly right, wrong): the set is small and team-written, so it shows
whether a model is usable, not a precise accuracy. docs/adr/0019-title-chat.md.
"""
import argparse
import json
from pathlib import Path
import re
import resource
import sys
import time
from types import SimpleNamespace

from ..config import DEFAULT_MOVIELENS, DEFAULT_SERIES
from .llm import LLMError
from .title_chat import MAX_TOKENS, TitleChat, facts

# What the recommender would hand over for each pick, and the viewer's evening.
PICKS = {
    'Arrival': ({'factors': {'taste': 0.6, 'mood': 0.3, 'intensity': 0.1}, 'because': ['Interstellar', 'Contact'],
                 'evidence': ['aliens', 'linguistics', 'thought-provoking'], 'popular': False},
                SimpleNamespace(mood='thoughtful', minutes=150)),
    'Toy Story': ({'factors': {'taste': 0.7, 'mood': 0.2}, 'because': ['Finding Nemo'],
                   'evidence': ['pixar', 'animation'], 'popular': False},
                  SimpleNamespace(mood='uplifting', minutes=100)),
    'Breaking Bad': ({'factors': {'taste': 0.8, 'intensity': 0.2}, 'because': [], 'evidence': ['crime', 'drama'],
                      'popular': True},
                     SimpleNamespace(mood='tense', minutes=60)),
}
QUESTIONS = [
    'Who directed it?',
    'Who is in it?',
    'What is it about, without spoilers?',
    'Why was this recommended to me?',
    'Is it scary? Is it OK for kids?',
    'Will it fit in the time I have tonight?',
    'Who composed the music?',   # not in the facts: should say Flicks doesn't know
    'Is it better than Alien?',  # a comparison the facts cannot support
]
THINKING = re.compile(r'<think>.*?(</think>|$)', re.S)  # an unclosed block too, while it is still thinking


def peak_mb():
    # ru_maxrss is in bytes on macOS and kilobytes on Linux.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e6 if sys.platform == 'darwin' else 1e3)


def ask(llm, messages):
    """(raw reply, seconds to the first visible words, seconds to the full reply, tokens)."""
    start, first, raw, tokens = time.perf_counter(), None, '', 0
    for chunk in llm.create_chat_completion(messages, stream=True, max_tokens=MAX_TOKENS, temperature=0.2):
        delta = chunk['choices'][0]['delta'].get('content')
        if not delta:
            continue
        tokens += 1
        raw += delta
        if first is None and THINKING.sub('', raw).strip():
            first = time.perf_counter() - start
    total = time.perf_counter() - start
    return raw, total if first is None else first, total, tokens


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('model', type=Path, help='A GGUF file')
    parser.add_argument('--cpu', action='store_true', help='Run on the CPU only')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--out', type=Path, help='Also write every answer and the summary as JSON')
    args = parser.parse_args(argv)
    from llama_cpp import Llama

    items = json.loads(DEFAULT_MOVIELENS.read_text())
    if DEFAULT_SERIES.is_file():
        items += json.loads(DEFAULT_SERIES.read_text())
    by_title = {item['title']: item for item in items}
    chat = TitleChat(SimpleNamespace(model=args.model.stem), [SimpleNamespace(title=t) for t in by_title])
    base = peak_mb()
    started = time.perf_counter()
    llm = Llama(model_path=str(args.model), n_ctx=2048, n_threads=args.threads, n_gpu_layers=0 if args.cpu else -1,
                verbose=False)
    load = time.perf_counter() - started
    rows = []
    for title, (pick, session) in PICKS.items():
        given = facts(by_title[title], pick, session)
        for question in QUESTIONS:
            raw, first, total, tokens = ask(llm, chat.messages(given, question))
            answer = THINKING.sub('', raw).strip()
            try:
                chat.check(answer, given, question)
                note = None
            except LLMError as error:
                note = str(error)
            rows.append({'title': title, 'question': question, 'answer': answer, 'withdrawn': note,
                         'cut_off': tokens >= MAX_TOKENS, 'first_s': round(first, 3), 'total_s': round(total, 3)})
            flags = ' [withdrawn]' * bool(note) + ' [cut off]' * rows[-1]['cut_off']
            print(f'[{first:.2f} s / {total:.2f} s]{flags} {title} | {question}\n    {answer}', flush=True)
    firsts = sorted(row['first_s'] for row in rows)
    totals = sorted(row['total_s'] for row in rows)
    summary = {'model': args.model.name, 'file_mb': round(args.model.stat().st_size / 1e6),
               'backend': 'cpu' if args.cpu else 'gpu', 'load_s': round(load, 2), 'added_mb': round(peak_mb() - base),
               'first_median_s': firsts[len(firsts) // 2], 'first_max_s': firsts[-1],
               'total_median_s': totals[len(totals) // 2], 'total_max_s': totals[-1],
               'withdrawn': sum(bool(row['withdrawn']) for row in rows), 'cut_off': sum(row['cut_off'] for row in rows)}
    print(json.dumps(summary, indent=1))
    if args.out:
        args.out.write_text(json.dumps({'summary': summary, 'rows': rows}, indent=1))


if __name__ == '__main__':
    main()
