# Small language models for the title chat and corner chat (November 2026)

A follow-up to [ADR 0019](adr/0019-title-chat.md), which picked Qwen2.5 1.5B and then Qwen3.5 2B (the
current default) from 24 hand-scored questions (`python -m flicks.assistant.title_chat_eval`).
This round tests nine models on 90 questions and six corner-chat conversations, on the team's
8 GB Apple M2, through Flicks' own code (`TitleChat`, `Concierge`, `EmbeddedChat`): same prompts, same
`/no_think`, same checks that withdraw an answer.

Scripts: [`scripts/llm_bench.py`](../scripts/llm_bench.py) runs the models; [`scripts/llm_bench_score.py`](../scripts/llm_bench_score.py)
scores them. Raw answers are in `work/llm-bench/` (not committed).

## Method

- **Title chat:** 10 titles (Arrival, Toy Story, Breaking Bad, The Shining, Paddington 2, Inception, Spirited
  Away, The Office, Mad Max: Fury Road, Get Out) × 9 questions: who directed it, who's in it, what it's
  about, why Flicks picked it, is it scary or OK for kids, does it fit tonight, who composed the music (never
  in the facts), is it better than Alien (a comparison the facts can't support), and a follow-up "And how
  long is it?" that uses the earlier turn. One viewer profile (liked Interstellar, The Martian, Up, Finding
  Nemo, Sherlock, The Grand Budapest Hotel; disliked Ted Lasso), mood "curious", 120 minutes.
- **Scoring:** rules per question, from the facts the model was given (see the script's docstring). Right
  means correct and grounded, including an honest "Flicks doesn't know". Partly means right, but with a name
  that isn't in the facts or more than 60 words. Real-world facts that Flicks wasn't given count against
  the answer: the test is groundedness. Score = (right + ½ partly) / 90.
- **Corner chat:** 6 scripted conversations, graded on the model's own wording: asks about time when it
  should, names at least two of the three picks, no lists, no leaked prompt, at most 70 words. "Kept" is how
  often the app's own check accepted the wording rather than falling back to Flicks' sentence.
- **Check on the scorer:** an independent grader (another model, not told which model wrote what) graded
  135 answers blind. It agreed exactly on 67% of them, and it found a bug in the cast rule (now fixed). It
  ranked Qwen3.5 2B first (87%) and graded LFM2.5 and Qwen2.5 1.5B lower than the rules did (both 72%).
  Treat differences under about 5 points as noise.
- **Safety:** one model at a time, each in its own process. A watchdog kills it if memory pressure stays
  critical for 2 s or it passes 3.5 GB. All files are 4-bit GGUFs, loaded text-only, checked against
  Hugging Face's SHA-256. Each configuration ran once at temperature 0.2.
- **Runtime:** llama-cpp-python 0.3.36 (the project's), except LFM3, which needs 0.3.37.

## Results

| Model (4-bit) | File | License | Score | Corner chat (kept) | Full answer: median / p90 / worst | First words, first question | Peak memory |
|---|---:|---|---:|---:|---|---:|---:|
| **Granite 4.0 1B, CPU only** | 1.0 GB | Apache 2.0 | **95%** | 6/6 (5) | 0.8 / 1.8 / 3.7 s | 1.8 s | 1.8 GB |
| Qwen3.5 2B, Metal (current default) | 1.4 GB | Apache 2.0 | 91% | 6/6 (3; 5 after fix 1) | 1.4 / 1.9 / 2.3 s | 0.7 s | 1.5 GB |
| Qwen3.5 2B, CPU | | | 91% | 6/6 (5) | 3.9 / 5.2 / 13.4 s | 3.0 s | 2.1 GB |
| LFM2.5 1.2B, CPU | 0.7 GB | LFM Open License | 90% | 6/6 (6) | 2.1 / 2.6 / 5.3 s | 1.8 s | 1.6 GB |
| LFM2.5 1.2B, Metal | | | 88% | 5/6 (6) | 0.6 / 0.8 / 1.2 s | 0.4 s | 0.9 GB |
| Qwen2.5 1.5B, CPU (previous default) | 1.0 GB | Apache 2.0 | 86% | 3/6 (3) | 0.8 / 1.8 / 2.6 s | 1.4 s | 1.7 GB |
| Qwen2.5 1.5B, Metal (previous default) | | | 85% | 3/6 (4) | 0.7 / 1.7 / 2.8 s | 0.4 s | 1.1 GB |
| Qwen3.5 0.8B, CPU | 0.6 GB | Apache 2.0 | 85% | 0/6 (5) | 1.3 / 1.9 / 3.9 s | 1.0 s | 1.4 GB |
| Qwen3.5 0.8B, Metal | | | 81% | 1/6 (5) | 0.5 / 0.8 / 1.3 s | 0.3 s | 0.8 GB |
| LFM3 1.7B, Metal (thinking off) | 1.1 GB | LFM Open License | 76% | 5/6 (4) | 1.5 / 2.6 / 2.8 s | 0.6 s | 1.3 GB |
| Qwen2.5 0.5B, Metal | 0.4 GB | Apache 2.0 | 74% | 1/6 (6) | 0.3 / 0.7 / 1.2 s | 0.1 s | 0.7 GB |
| Llama 3.2 1B, Metal | 0.8 GB | Llama 3.2 | 69% | 1/6 (3) | 0.2 / 0.6 / 1.3 s | 0.3 s | 1.0 GB |
| Gemma 3 1B, Metal | 0.8 GB | Gemma | 66% | 6/6 (5) | 0.5 / 0.8 / 1.0 s | 0.3 s | 1.1 GB |
| Granite 4.0 1B, Metal | | | 0% | 0/6 | output is only "@@@@" | | 1.4 GB |

Right answers out of 10, per question (top models):

| Model | director | cast | plot | why | kids | fits | composer | compare | length |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Granite 4.0 1B, CPU | 10 | 9 | 10 | 10 | 7 | 8 | 10 | 10 | 10 |
| Qwen3.5 2B, Metal | 5 | 9 | 8 | 10 | 10 | 9 | 10 | 10 | 10 |
| LFM2.5 1.2B, CPU | 8 | 10 | 8 | 10 | 9 | 5 | 10 | 10 | 10 |
| Qwen2.5 1.5B, Metal | 10 | 9 | 4 | 9 | 5 | 6 | 10 | 7 | 9 |

## What we learned

- **Granite 4.0 1B is the strongest here, but only on the CPU.** Its answers are short, grounded and
  honest about gaps. Its mistakes: "suitable for kids" with no rating, and "fits your 120-minute slot" for
  the 148-minute Inception. On Metal it prints only "@" in both runtime versions, so on a Mac it needs
  `gpu_layers=0` (`--llm-cpu`). It reuses its work on follow-ups (0.1 s to the first word after the first
  question), and no answer took over 5 s.
- **Qwen3.5 2B is the best on Metal.** It never claimed a rating, it declined every comparison, and it
  agrees with the code on "fits tonight". Its odd failure: 5 times out of 10 it answered "Who directed
  it?" with "Flicks only has details about this one." Two costs: it can't reuse earlier work on the same
  title, so every question reads the facts again (0.7 s on Metal, 3 s on the CPU), and on the CPU 12 of 90
  answers took over 5 s (13 s at worst). ADR 0019's 24 questions saw 4.2 s at worst; the longer answers here
  (plots, pitches) show the tail.
- **LFM2.5 1.2B is the best small model.** It's 0.7 GB and fast on Metal. The blind grader found it vaguer
  than the rules did ("you might find it fitting tonight"). Its license is free only below US$10M a year in
  revenue, unlike Apache.
- **LFM3 1.7B underperforms its published scores here.** Its template thinks by default, so the first run
  answered with its reasoning ("We need to answer the question…"). With `enable_thinking=false` it is
  verbose (27 of 90 answers over 60 words) and leaks a stray `</think>`. It also needs llama-cpp-python
  0.3.37.
- **Qwen2.5 1.5B (the previous default) is middling.** It rarely uses its own "fits tonight" fact, pads plots
  with cast and crew from memory, and declined only 7 of 10 comparisons.
- **The machine:** before any model loaded, 9 to 10 GB of swap was already in use, with memory pressure
  at "warning" (Claude, Discord, Outlook and ChatGPT were open). One load of Qwen3.5 2B briefly drove
  pressure to "critical". The same run then passed cleanly. A 1 to 2 GB model is fine. The October freeze
  came from a 4B model plus its vision file on a machine already this full.

## Bugs this found in Flicks

1. **The corner chat threw away good pitches (fixed).** The pitch check allowed only the three picks' names,
   so a pitch that said "like Finding Nemo, which you liked" or repeated the viewer's own "like The Martian"
   fell back to Flicks' plain sentence. That happened to 3 of Qwen3.5 2B's 6 replies. The check now also
   allows the picks' "because you liked" titles and the title the viewer asked about, even when typed in
   lower case. After the fix, Qwen3.5 2B kept 5 of 6. The one still rejected named "King Arthur", which is a
   catalogue title the model wasn't given.
2. **A stray `</think>` was shown (fixed).** `EmbeddedChat` stripped a thinking block only when it opened
   with `<think>`. Templates that open the block themselves (LFM3) left a closing tag and a second copy of
   the answer. A `</think>` with no opening tag now ends the answer.
3. **Some models must run on the CPU.** Granite is broken on Metal, so "use the GPU" can't be one global
   default if Granite ships.
4. **The `/no_think` check is by name.** `'qwen3' in model` catches Qwen3 and Qwen3.5. Models with an
   `enable_thinking` template switch (LFM3) need it set in the template instead.

## Next

- Rerun Granite 4.0 1B (CPU), Qwen3.5 2B (Metal) and LFM2.5 1.2B on a second, larger set of titles, each
  three times. A 4-point lead on one run is not settled.
- Then decide the default in an ADR 0019 amendment. On this evidence: Granite 4.0 1B on the CPU everywhere
  (one setting for Mac, Windows and Linux, Apache 2.0, no answer over 5 s), with Qwen3.5 0.8B as the
  low-memory fallback.
- Not tested: Gemma 4 E2B and Qwen3.5 4B (3 GB files, left out on this machine), Granite 4.0 H 1B (the
  hybrid version), and Inkling, which needs two data-centre GPUs and can't run locally.
