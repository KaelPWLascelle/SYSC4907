"""Score scripts/llm_bench.py output: right / partly / wrong per answer, from the facts the model was given.

Rules per question (the "facts" are what TitleChat sent the model):
  director, cast  the name(s) the description gives, or an honest "Flicks doesn't know"; no invented names
  plot            overlaps the description and invents no names
  why             cites a liked title, a shared theme or a ranking reason from the facts
  kids            no invented age rating; asserting "fine for kids" without one is only partly right
  fits            agrees with the code's own yes/no for tonight: the time, and the mood (the recommender's test)
  composer        "doesn't know" (no title's facts name a composer)
  compare         declines to compare (Flicks only has this title's details)
  length          gives the runtime (or episode length) from the facts
An answer that is right but over 60 words, or names a person/title not in the facts, is "partly".
A reply the app withdrew (TitleChat.check) is counted as "withdrawn": wrong, but never shown.

    .venv/bin/python scripts/llm_bench_score.py work/llm-bench/*.jsonl [--examples N]
"""
import argparse
import json
from pathlib import Path
import re
import statistics
import sys

DONT_KNOW = re.compile(
    r"(don'?t|do not|doesn'?t|does not|can'?t|cannot|isn'?t|is not|not) (know|have|include|contain|say|"
    r"mention|tell|provide|list|specif|available|given|in the|part of|sure)|no (information|details|info|data)|"
    r"unknown|not known|isn'?t (listed|mentioned|specified|provided|available)|only (has|have) (details|info)|"
    r"not (listed|mentioned|specified|provided|available|included)|unable to", re.I)
RATING = re.compile(r'\b(PG-13|PG|NC-17|TV-MA|TV-14|TV-PG|TV-Y7?|rated [GR]\b|R-rated|G-rated|rated PG)', re.I)
KID_CLAIM = re.compile(r'(suitable|appropriate|fine|great|good|perfect|safe|ok|okay) for (kids|children|'
                       r'the whole family|families|young)|family[- ]friendly|kid[- ]friendly', re.I)
YES = re.compile(r"^\W*(yes|yep|it does|it fits|absolutely|sure)\b|\b(can|could) (watch|fit|finish) it|\bfitting\b|\bfits (?:well |nicely |comfortably |easily )?"
                 r"(?:in|within|into)|\b(?:it )?fits\b(?!.*\bnot\b)|enough time|\bwithin\b", re.I)
NO = re.compile(r"^\W*no\b|doesn'?t fit|does not fit|won'?t fit|will not fit|not fit|too long|longer than|"
                r"exceeds|more than (?:the|your)|not enough time|over your|runs over|rather than|may not suit|"
                r"(?:doesn'?t|does not|may not|might not|isn'?t|is not)\b[\w\s'-]{0,20}\b(?:match|suit)", re.I)
VERDICT = re.compile(r"^\W*(yes|no)\b|\bis (better|worse|superior) than(?! the other)|\b(more|less) (enjoyable|impressive) than",
                     re.I)
# Capitalised runs that are not names.
COMMON = {'The', 'A', 'An', 'It', 'Its', 'This', 'That', 'Flicks', 'You', 'Your', 'Yes', 'No', 'I', 'If', 'In',
          'However', 'But', 'And', 'Is', 'He', 'She', 'They', 'Based', 'Since', 'As', 'Unfortunately', 'Sorry',
          'With', 'While', 'Also', 'For', 'Not', 'There', 'Here', 'So', 'Because', 'Both', 'One', 'Each'}


def norm(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', s.lower())).strip()


def invented_names(answer, given, question):
    """Runs of two or more capitalised words that appear nowhere in the facts or the question."""
    known = norm(json.dumps(given, ensure_ascii=False) + ' ' + question)
    bad = []
    for run in re.findall(r"\b[A-Z][\w'\-]+(?:\s+(?:of|the|de|van|von|and)?\s*[A-Z][\w'\-]+)+", answer):
        words = run.split()
        while words and words[0] in COMMON:
            words = words[1:]
        # "Finding Nemo and Up" is two names: each part must be in the facts.
        parts = [p.strip() for p in re.split(r'\band\b', ' '.join(words)) if p.strip()]
        if len(words) >= 2 and any(norm(p) not in known for p in parts):
            bad.append(' '.join(words))
    return bad


def directors(description):
    """Surnames after "directed by", read as the app reads them (title_chat.directors); "the Wachowskis" too."""
    from flicks.assistant.title_chat import directors as named
    names = [n.split()[-1] for n in named(description)]
    if not names and (m := re.search(r'directed by the ([A-Z][\w\'-]+)', description)):
        names = [m.group(1)]
    return names


def cast_names(description):
    names = []
    for m in re.finditer(r'\b(?:stars|starring|co-stars)\s+((?:[A-Z][\w\'\-]+\s?){2,3})', description):
        names.append(m.group(1).split()[-1])
    return names


def overlap(answer, description):
    stop = set(['the', 'a', 'an', 'and', 'of', 'to', 'in', 'is', 'it', 'its', 'as', 'with', 'for', 'on', 'by', 'at', 'from', 'that', 'this', 'his', 'her', 'their', 'who', 'are', 'was', 'be'])
    a = {w for w in norm(answer).split() if w not in stop and len(w) > 3}
    d = {w for w in norm(description).split() if w not in stop and len(w) > 3}
    return len(a & d)


def grade(row):
    """('right'|'partly'|'wrong'|'withdrawn', reason)."""
    if not row['ok']:
        return 'withdrawn', row.get('note') or 'withdrawn'
    answer, given, q = row['answer'], row['given'], row['q']
    lower = answer.lower()
    names = invented_names(answer, given, row['question'])
    abstains = bool(DONT_KNOW.search(answer))
    desc = given['description']
    if q == 'director':
        who = directors(desc)
        ok = any(w.lower() in lower for w in who) if who else abstains
        why = f'wanted {who or "an abstention"}'
    elif q == 'cast':
        # Right: names people the description names (and invents none), or says Flicks doesn't know.
        named = [n for n in re.findall(r"\b[A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+)+", answer) if n in desc]
        ok = (bool(named) and not names) or (abstains and not names)
        why = 'wanted names from the description, or an abstention'
    elif q == 'plot':
        ok = overlap(answer, desc) >= 3 and not abstains
        why = 'should follow the description'
    elif q == 'why':
        reasons = given.get('why Flicks picked it', {})
        cues = [*reasons.get('because you liked', []), *reasons.get('themes shared with what you liked', [])]
        cues += [w for r in reasons.get('main reasons', []) for w in norm(r).split() if len(w) > 5]
        ok = any(c.lower() in lower for c in cues)
        why = 'should cite a liked title, theme or reason'
    elif q == 'kids':
        if RATING.search(answer):
            return 'wrong', f'invented rating: {RATING.search(answer).group(0)}'
        ok = bool(re.search(r'scar|intens|gentle|tense|calm|kid|child|famil|age|rating|young', answer, re.I))
        if ok and KID_CLAIM.search(answer) and not abstains:
            return 'partly', 'asserts kid suitability without a rating'
        why = 'should talk about intensity or age'
    elif q == 'fits':
        evening = given['your evening']
        time_ok = next(v for k, v in evening.items() if 'fit' in k)
        mood_ok = evening['mood'] == 'any' or evening['mood'] in given.get('moods', [])
        fits = time_ok and mood_ok
        text = answer.replace('\u2019', "'")
        says_no, says_yes = bool(NO.search(text)), bool(YES.search(text))
        ok = (says_yes and not says_no) if fits else says_no
        why = f'code says time fits={time_ok}, mood matches={mood_ok}'
    elif q == 'composer':
        ok = abstains and not names
        why = 'composer is not in the facts'
    elif q == 'compare':
        ok = abstains and not VERDICT.search(answer)
        why = 'should decline to compare'
    elif q == 'length':
        minutes = given.get('minutes') or given.get('minutes per episode')
        ok = str(minutes) in answer or (minutes and f'{minutes // 60} hour' in lower and minutes % 60 == 0)
        why = f'wanted {minutes} minutes'
    else:
        raise ValueError(q)
    if not ok:
        return 'wrong', why
    if names:
        return 'partly', f'not in the facts: {", ".join(names[:3])}'
    if len(answer.split()) > 60:
        return 'partly', f'{len(answer.split())} words'
    return 'right', ''


def grade_corner(row):
    """The corner chat's wording: ('right'|'wrong'|'fallback', reason). Fallback = Flicks' own sentence."""
    # Graded on the model's own words, even when the app fell back to its sentence (its check is stricter).
    text = ' '.join(re.sub(r'<think>.*?</think>', '', row['raw'], flags=re.S).split())
    if not text:
        return 'wrong', 'no text'
    if row['step'] == 'time':
        ok = '?' in text and re.search(r'how (much time|long)|minutes|hours?\b', text, re.I) and \
            not re.search(r'spent|so far|left in|watching this', text, re.I)
        return ('right', '') if ok else ('wrong', 'should ask how much time they have')
    if row['step'] == 'mood':
        ok = '?' in text and re.search(r'mood|feel|genre|kind of|type of|loved|like to watch|in the mood', text, re.I)
        return ('right', '') if ok else ('wrong', 'should ask what they are in the mood for')
    named = sum(1 for t in row['picks'] if t.lower() in text.lower())
    if re.search(r'concierge|the viewer|\bfacts?\b|^\W*flicks[,:]', text, re.I):
        return 'wrong', 'leaks the prompt'
    if re.search(r'(^|\s)[1-3][.)]\s|\*\*|^- ', text):
        return 'wrong', 'list or markdown'
    if named < 2:
        return 'wrong', f'names {named} of the 3 picks'
    if len(text.split()) > 70:
        return 'wrong', f'{len(text.split())} words'
    return 'right', ''


def load(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    return rows[0], rows[1:]


def pct(values, p):
    values = sorted(v for v in values if v is not None)
    return values[min(len(values) - 1, round(p * (len(values) - 1)))] if values else float('nan')


def summarise(path):
    run, rows = load(path)
    titles = [r for r in rows if r['kind'] == 'title']
    graded = [(r, *grade(r)) for r in titles]
    counts = {k: sum(1 for _, g, _ in graded if g == k) for k in ('right', 'partly', 'wrong', 'withdrawn')}
    conc = [r for r in rows if r['kind'] == 'concierge']
    load_row = next((r for r in rows if r['kind'] == 'load'), {})
    thinking = sum(1 for r in titles + conc if '<think>' in r.get('raw', '') and
                   re.sub(r'\s', '', r['raw'].split('</think>')[0].replace('<think>', '')))
    firsts = [r for r in titles if r['q'] == 'director']        # first question per title: reads the facts
    return {
        'label': run['label'], 'killed': run['killed'], 'peak_rss_mb': run['peak_rss_mb'],
        'peak_pressure': run['peak_pressure'], 'swap_delta_mb': run['swap_used_after_mb'] - run['swap_used_before_mb'],
        'load_s': load_row.get('seconds'), 'n': len(titles), **counts,
        'first_word_s': statistics.median([r['first'] for r in titles if r['first']] or [float('nan')]),
        'first_word_cold_s': statistics.median([r['first'] for r in firsts if r['first']] or [float('nan')]),
        'total_med_s': statistics.median([r['total'] for r in titles] or [float('nan')]),
        'total_p90_s': pct([r['total'] for r in titles], 0.9), 'total_max_s': max([r['total'] for r in titles] or [0]),
        'words_med': statistics.median([len((r.get('answer') or r['text']).split()) for r in titles] or [0]),
        'thinking': thinking,
        'concierge_worded': sum(1 for r in conc if grade_corner(r)[0] == 'right'), 'concierge_n': len(conc),
        'concierge_accepted': sum(1 for r in conc if r['model']),
        'concierge_med_s': statistics.median([r['total'] for r in conc] or [float('nan')]),
        'by_q': {q: [g for r, g, _ in graded if r['q'] == q] for q in dict.fromkeys(r['q'] for r in titles)},
        'graded': graded, 'concierge': conc,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('files', nargs='+')
    parser.add_argument('--examples', type=int, default=0, help='print N failing answers per model')
    parser.add_argument('--json', help='write the summary table here')
    args = parser.parse_args(argv)
    results = [summarise(f) for f in args.files]
    results = [s for s in results if s['n']] + [s for s in results if not s['n']]
    results.sort(key=lambda s: (-(s['right'] + 0.5 * s['partly']), s['total_med_s']))
    print('| Model | Right | Partly | Wrong | Withdrawn | Score | Corner chat right | First words (cold / warm) | '
          'Full answer median / p90 / max | Load | Peak RSS | Pressure | Thinking |')
    print('|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|')
    for s in results:
        score = (s['right'] + 0.5 * s['partly']) / max(1, s['n'])
        print(f"| {s['label']}{' (killed: ' + s['killed'] + ')' if s['killed'] else ''} | {s['right']} | {s['partly']} | "
              f"{s['wrong']} | {s['withdrawn']} | {score:.0%} | {s['concierge_worded']}/{s['concierge_n']} ({s['concierge_accepted']} kept) | "
              f"{s['first_word_cold_s']:.2f} / {s['first_word_s']:.2f} s | "
              f"{s['total_med_s']:.2f} / {s['total_p90_s']:.2f} / {s['total_max_s']:.1f} s | {s['load_s'] or 0:.1f} s | "
              f"{s['peak_rss_mb']:.0f} MB | {s['peak_pressure']} | {s['thinking']} |")
    qs = list(results[0]['by_q']) if results else []
    print('\nRight answers per question type (share of titles):\n')
    print('| Model | ' + ' | '.join(qs) + ' |')
    print('|---|' + '---:|' * len(qs))
    for s in [s for s in results if s['n']]:
        print(f"| {s['label']} | " + ' | '.join(f"{s['by_q'][q].count('right') / max(1, len(s['by_q'][q])):.0%}" for q in qs) + ' |')
    if args.json:
        Path(args.json).write_text(json.dumps([{k: v for k, v in s.items() if k not in ('graded', 'concierge')}
                                               for s in results], indent=1))
    for s in results[:None] if args.examples else []:
        print(f"\n### {s['label']}")
        bad = [(r, g, why) for r, g, why in s['graded'] if g != 'right'][:args.examples]
        for r, g, why in bad:
            print(f"- [{g}] {r['given']['title']} / {r['question']} -> {(r.get('answer') or r.get('note') or '')[:220]!r} ({why})")
        for c in s['concierge']:
            g, why = grade_corner(c)
            print(f"- [corner {g}{'' if c['model'] else ', app fell back'}] {c['texts'][-1]!r} -> {c['raw'][:200]!r} {why}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
