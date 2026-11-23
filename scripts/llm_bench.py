"""Benchmark small GGUF models on Flicks' own language-model jobs (docs/adr/0019-title-chat.md).

Two jobs, run through the real code paths (TitleChat and Concierge) so prompts, /no_think and the
grounding checks are exactly what the app does:
  * title chat: 10 titles x 9 questions (the last a follow-up that uses the history);
  * corner chat: 6 scripted conversations, scored on whether the model's wording survives the checks.

Each model runs in its own child process, one at a time, under a watchdog that kills the child if macOS
memory pressure turns critical or the child's resident memory passes a ceiling. Raw results go to
work/llm-bench/<label>.jsonl; scripts/llm_bench_score.py scores them.

    .venv/bin/python scripts/llm_bench.py --cpu ~/.flicks/models/Qwen3.5-2B-Q4_K_M.gguf ...
"""
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'work'/'llm-bench'

TITLES = ['ml164179', 'ml1', 'tv169', 'ml1258', 'ml178827', 'ml79132', 'ml5618', 'tv526', 'ml122882', 'ml168250']
LIKED = ['ml109487', 'ml134130', 'ml68954', 'ml6377', 'tv335', 'ml109374']   # Interstellar, The Martian, Up,
DISLIKED = ['tv44458']                                                          # Finding Nemo, Sherlock, Budapest; Ted Lasso
QUESTIONS = [
    ('director', 'Who directed it?'),
    ('cast', "Who's in it?"),
    ('plot', "What's it about?"),
    ('why', 'Why did Flicks pick this for me?'),
    ('kids', 'Is it scary? Is it OK for my kids?'),
    ('fits', 'Does it fit tonight?'),
    ('composer', 'Who composed the music?'),
    ('compare', 'Is it better than Alien?'),
]
FOLLOW_UP = ('length', 'And how long is it?')   # asked after "Who directed it?", with that turn as history
CONVERSATIONS = [
    ['something funny and light'],
    ['something funny and light', 'about 90 minutes'],
    ["I'm exhausted, nothing scary"],
    ['a mind-bending sci-fi film', 'I have all night'],
    ['a series to binge with my partner', 'an hour or so'],
    ['something like The Martian but lighter', 'two hours'],
]


def services():
    from flicks.__main__ import _sidecar
    from flicks.config import DEFAULT_SERIES, Settings, default_films
    from flicks.services import build_services
    catalog = default_films()
    db = Path(tempfile.mkdtemp())/'bench.sqlite3'
    settings = Settings(db=db, catalog=catalog, neighbours=_sidecar(catalog), series=DEFAULT_SERIES,
                        couch=False, ask_student=Settings.ask_student)
    return build_services(settings)


def child(path, gpu, threads):
    """Run every task against one model; print one JSON line per answer."""
    from flicks.assistant.concierge import Concierge
    from flicks.assistant.embedded import EmbeddedChat
    from flicks.assistant.narrator import Narrator
    from flicks.assistant.title_chat import TitleChat, facts
    from flicks.core import Session

    svc = services()
    chat = EmbeddedChat(path, gpu_layers=-1 if gpu else 0, threads=threads, idle_seconds=3600)
    raw = []
    llm = chat._load()
    template = llm.metadata.get('tokenizer.chat_template', '')
    if 'enable_thinking' in template:
        # Models whose template thinks by default (LFM3) answer with their reasoning inside a 120-token cap.
        # Flicks would need the same switch to ship one: the template's own enable_thinking=false.
        from llama_cpp.llama_chat_format import Jinja2ChatFormatter
        eos = llm._model.token_get_text(llm._model.token_eos())
        bos = llm._model.token_get_text(llm._model.token_bos())
        llm.chat_handler = Jinja2ChatFormatter('{%- set enable_thinking = false -%}' + template, eos, bos,
                                               stop_token_ids=[llm._model.token_eos()]).to_chat_handler()
    emit({'kind': 'template', 'thinking_switch': 'enable_thinking' in template})
    original = llm.create_chat_completion

    def recording(messages, **options):          # keep the raw stream, thinking included
        for chunk in original(messages, **options):
            raw.append(chunk['choices'][0]['delta'].get('content') or '')
            yield chunk
    llm.create_chat_completion = recording
    emit({'kind': 'load', 'seconds': chat.load_seconds})

    feedback = {**{i: 1 for i in LIKED}, **{i: -1 for i in DISLIKED}}
    session = Session(mood='curious', minutes=120)
    title_chat = TitleChat(chat, svc.catalog)

    def ask(given, question, history=()):
        raw.clear()
        start, first, text, final = time.perf_counter(), None, '', None
        for event in title_chat.stream(given, question, history):
            if 'delta' in event:
                first = first or time.perf_counter()
                text += event['delta']
            else:
                final = event
        end = time.perf_counter()
        return {'first': first and first - start, 'total': end - start, 'text': text, 'raw': ''.join(raw),
                'ok': final['ok'], 'answer': final.get('answer'), 'note': final.get('note')}

    for content_id in TITLES:
        pick = svc.recommender.explain_item(feedback, session, content_id)
        given = facts(pick['content'], pick, session)
        for key, question in QUESTIONS:
            emit({'kind': 'title', 'id': content_id, 'q': key, 'question': question, 'given': given,
                  **ask(given, question)})
            if key == 'director':
                history = [{'question': question, 'answer': last_answer()}]
        emit({'kind': 'title', 'id': content_id, 'q': FOLLOW_UP[0], 'question': FOLLOW_UP[1], 'given': given,
              **ask(given, FOLLOW_UP[1], history)})

    concierge = Concierge(svc.recommender, svc.titles, svc.interpreter, svc.similar, chat,
                          Narrator(chat, svc.catalog))
    for texts in CONVERSATIONS:
        messages = []
        for i, t in enumerate(texts):
            if i:
                messages.append({'role': 'assistant', 'text': 'OK.'})
            messages.append({'role': 'user', 'text': t})
        raw.clear()
        start, first, final, picks = time.perf_counter(), None, None, []
        for event in concierge.converse(feedback, Session(), messages):
            if 'delta' in event:
                first = first or time.perf_counter()
            if 'picks' in event:
                picks = [p['content']['title'] for p in event['picks']]
            if event.get('done'):
                final = event
        emit({'kind': 'concierge', 'texts': texts, 'first': first and first - start,
              'total': time.perf_counter() - start, 'step': final['step'], 'text': final['text'],
              'model': final['model'], 'picks': picks, 'raw': ''.join(raw)})
    emit({'kind': 'end', 'max_rss_mb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20})
    sys.stdout.flush()
    os._exit(0)   # skip llama.cpp's Metal teardown, which aborts at interpreter exit


_last = {}


def emit(row):
    if row.get('kind') == 'title':
        _last['answer'] = row.get('answer') or row.get('text') or ''
    print(json.dumps(row), flush=True)


def last_answer():
    return _last.get('answer', '')


def pressure():
    out = subprocess.run(['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


def swap_used_mb():
    out = subprocess.run(['sysctl', '-n', 'vm.swapusage'], capture_output=True, text=True).stdout
    return float(out.split('used = ')[1].split('M')[0])


def rss_mb(pid):
    out = subprocess.run(['ps', '-o', 'rss=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return int(out or 0) / 1024


def run(path, gpu, threads, ceiling_mb):
    label = f"{Path(path).stem}.{'metal' if gpu else 'cpu'}"
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT/f'{label}.jsonl'
    before = swap_used_mb()
    errors = open(OUT/f'{label}.stderr', 'w')  # noqa: SIM115 - the child writes to it until it exits
    proc = subprocess.Popen([sys.executable, __file__, '--child', str(path), '--threads', str(threads),
                             *(['--cpu'] if not gpu else [])], stdout=subprocess.PIPE, stderr=errors,
                            text=True, cwd=ROOT)
    lines = []
    reader = threading.Thread(target=lambda: lines.extend(line.rstrip('\n') for line in proc.stdout if line.strip()), daemon=True)
    reader.start()
    peak_rss, peak_pressure, killed, critical, critical_samples = 0.0, 0, None, 0, 0
    started = time.time()
    while True:
        if proc.poll() is not None:
            reader.join(5)
            break
        peak_rss = max(peak_rss, rss_mb(proc.pid))
        level = pressure()
        peak_pressure = max(peak_pressure, level)
        critical = critical + 1 if level >= 4 else 0
        critical_samples += level >= 4
        # Critical for 2 s in a row (a brief spike while weights page in is normal), or too big.
        if critical >= 4 or peak_rss > ceiling_mb:
            killed = f'pressure critical for {critical / 2:.1f} s' if critical >= 4 else f'resident memory {peak_rss:.0f} MB'
            proc.kill()
            proc.wait()
            break
        time.sleep(0.5)
    summary = {'kind': 'run', 'label': label, 'file': Path(path).name, 'gpu': gpu, 'threads': threads,
               'seconds': time.time() - started, 'peak_rss_mb': peak_rss, 'peak_pressure': peak_pressure, 'critical_seconds': critical_samples / 2,
               'swap_used_before_mb': before, 'swap_used_after_mb': swap_used_mb(), 'killed': killed,
               'exit': proc.returncode, 'rows': len(lines)}
    errors.close()
    target.write_text('\n'.join([json.dumps(summary), *lines]) + '\n')
    print(json.dumps(summary), flush=True)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('models', nargs='+')
    parser.add_argument('--cpu', action='store_true', help='CPU only (no Metal)')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--ceiling-mb', type=float, default=3500)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return child(args.models[0], not args.cpu, args.threads)
    for model in args.models:
        run(model, not args.cpu, args.threads, args.ceiling_mb)
        time.sleep(5)   # let memory settle between models


if __name__ == '__main__':
    sys.exit(main())
