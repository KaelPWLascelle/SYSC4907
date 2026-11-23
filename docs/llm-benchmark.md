# Small language models for the title chat and corner chat (November 2026)

A follow-up to [ADR 0019](adr/0019-title-chat.md), which picked Qwen2.5 1.5B and then Qwen3.5 2B (the
default before this benchmark) from 24 hand-scored questions (`python -m flicks.assistant.title_chat_eval`).
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
  Hugging Face's SHA-256. Each configuration ran once at temperature 0.2 (the confirmatory run below: three times).
- **Runtime:** llama-cpp-python 0.3.36 (the project's), except LFM3, which needs 0.3.37.

## Results

| Model (4-bit) | File | License | Score | Corner chat (kept) | Full answer: median / p90 / worst | First words, first question | Peak memory |
|---|---:|---|---:|---:|---|---:|---:|
| **Granite 4.0 1B, CPU only** | 1.0 GB | Apache 2.0 | **95%** | 6/6 (5) | 0.8 / 1.8 / 3.7 s | 1.8 s | 1.8 GB |
| Qwen3.5 2B, Metal (previous default) | 1.4 GB | Apache 2.0 | 91% | 6/6 (3; 5 after fix 1) | 1.4 / 1.9 / 2.3 s | 0.7 s | 1.5 GB |
| Qwen3.5 2B, CPU | | | 91% | 6/6 (5) | 3.9 / 5.2 / 13.4 s | 3.0 s | 2.1 GB |
| LFM2.5 1.2B, CPU | 0.7 GB | LFM Open License | 90% | 6/6 (6) | 2.1 / 2.6 / 5.3 s | 1.8 s | 1.6 GB |
| LFM2.5 1.2B, Metal | | | 88% | 5/6 (6) | 0.6 / 0.8 / 1.2 s | 0.4 s | 0.9 GB |
| Qwen2.5 1.5B, CPU (older default) | 1.0 GB | Apache 2.0 | 86% | 3/6 (3) | 0.8 / 1.8 / 2.6 s | 1.4 s | 1.7 GB |
| Qwen2.5 1.5B, Metal (older default) | | | 85% | 3/6 (4) | 0.7 / 1.7 / 2.8 s | 0.4 s | 1.1 GB |
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

## Confirmatory run (second title set)

The three leaders, run again on 20 new titles (12 films, 5 series and two traps: *Parasite* (1982), a horror
film that shares a name with the 2019 one, and *Frozen* (2010), a survival horror film that shares a name
with the Disney one), with a different viewer (mood "relaxing", 100 minutes), the same 9 questions (180 in
all), and six new corner-chat conversations. Each configuration ran three times.

| Model (4-bit) | Rules score | Blind grader | Corner chat (kept) | Full answer: median / p90 / worst | Peak memory |
|---|---:|---:|---:|---|---:|
| **Granite 4.0 1B, CPU** | **89%** | **77%** | 6/6 (5) | 0.6 / 1.6 / 3.3 s | 1.6 to 2.0 GB |
| Qwen3.5 2B, CPU | 87% | | 6/6 (6) | 3.6 to 6.8 / 6 to 8 / 10 s | 1.9 to 2.4 GB |
| Qwen3.5 2B, Metal | 86% | 66% | 6/6 (5) | 1.3 / 1.7 / 2.1 s | 1.0 to 1.7 GB |
| LFM2.5 1.2B, Metal | 82% | 71% | 6/6 (5) | 0.6 / 0.8 / 0.9 s | 0.8 to 1.1 GB |
| LFM2.5 1.2B, CPU | 81% | | 6/6 (6) | 1.8 / 2.1 / 2.5 s | 1.6 to 1.7 GB |

- **Repeats only test speed.** The three runs of each configuration gave the same answers word for word, so
  the score has no run-to-run spread at temperature 0.2. Speed was steady too. One exception: Qwen on the
  CPU varied from 3.6 to 6.8 s median between runs, because other apps were busy. A 25.8 s answer in its
  third run came when the laptop went to sleep, and is left out above.
- **Blind check, now including Granite.** An independent grader, not told which model wrote what, graded 45
  answers from each of the three (the same 5 titles per question for each). It ranked Granite first (77%),
  then LFM2.5 (71%), then Qwen3.5 2B (66%). It agreed exactly with the rules on 87 of 135. It was stricter
  than the rules in two places:
  - It counts Qwen's cautious "Flicks doesn't know if it's OK for kids" as wrong when the facts plainly say
    "intense crime" or "horror".
  - It counts "Flicks only has details about this one" as wrong when the description names the director.
- **Granite's lead held on both sets and with both graders.** It was 95% on the first set and 89% on the
  second. Per question, it was weak on kids (12 of 20 right) and fits (14 of 20). It is the only one of the
  three that
  claims a film is fine for children without a rating: "The Godfather … suitable for all ages", and
  "Fleabag … not inappropriate for kids". Qwen3.5 2B instead declines (20 of 20 kids answers right by the
  rules), but answered "Who directed it?" correctly only 10 times out of 20.
- **"Does it fit tonight?" is weak for all three.** All three said the horror *Parasite* or *Frozen* "fits
  your relaxing evening perfectly". Qwen and LFM2.5 also miscounted runtimes against the 100 minutes. The
  answer to this question already exists in code (`fits the time you have`), but no model reliably uses
  the mood half.
- **Neither trap fooled the facts.** No model described the Disney *Frozen* or the 2019 *Parasite*. The
  facts won over what the models remember.

## Recommendation

- **Plugin default (`flicks setup --model`): Granite 4.0 1B, run on the CPU.** It is the best on both title
  sets and with both graders, the fastest on the CPU (0.6 s typical, under 5.5 s at worst), Apache 2.0, a
  1.0 GB file, and one setting for every platform. On a Mac it must have `gpu_layers=0`, because it is
  broken on Metal.
- **What to tell users on most computers:** Granite 4.0 1B. On a Mac with 8 GB or less and other apps
  open, LFM2.5 1.2B on Metal is the lighter choice (0.8 to 1.1 GB, under 1 s per answer, 82%), but its
  license is free only under US$10M a year in revenue.
- **Done (same PR):** Granite is now the `flicks setup --model` download. It always runs on the CPU, and a
  "fine for kids" claim with no age rating is replaced with Flicks' own sentence built from intensity and
  genres. On the second title set, that check caught all 8 of Granite's claims and none of its 12
  hedged answers.

## Customization round (code checks, greedy decoding)

A review of customization options (sampling, constrained decoding, Granite's prompt features, LoRA
fine-tuning, activation steering, guard models, hallucination checkers) found the cheapest fix for these
failures: let code work out what it can know for certain, and let the model only word it. This round
added:
- **Facts:** whether the title matches the mood asked for (the recommender's own test), and the
  director's name when the description gives one.
- **Checks that put Flicks' own sentence in place of the model's:** an answer that contradicts the code's
  yes/no for tonight ("fits your relaxing evening perfectly" about a horror film), or misses a director the
  description names ("Flicks only has details about this one"), now gets Flicks' own sentence. This joins
  the kids check.
- **Decoding and length:** temperature 0 (greedy, as IBM recommends for Granite 4), repeat penalty
  unchanged at 1.0, and answers cut to three sentences.
- **Granite's "documents" mode**, tried as a benchmark variant (`--documents`).

Scored with the stricter rules (the fits rule now includes the mood; the director rule reads names as
the app does, which also changes the earlier rows):

| Model | Set 2 before | Set 2 after | Blind before | Blind after | Set 1 after |
|---|---:|---:|---:|---:|---:|
| Granite 4.0 1B, CPU | 88% | **96%** | 77% | 78% | 98% (87% before) |
| Qwen3.5 2B, Metal | 84% | **97%** | 66% | 78% | |
| LFM2.5 1.2B, Metal | 86% | 91% | 71% | 73% | |
| Granite 4.0 1B, documents mode | | 90% | | | |

- **By the rules, the checks lift every model**, mostly on "fits tonight" (Granite went from 45% to
  100%, Qwen from 35% to 100%) and on directors (Qwen went from 55% to 95%). The rules and the checks
  share their logic, so the blind grader is the fairer measure.
- **Blind, the gain is real for Qwen and small for Granite.** Qwen gained 12 points, because its two
  failures were exactly the ones the checks catch. Granite gained 1 point, because its remaining
  mistakes are ones no check catches:
  - weak "why" answers that list raw theme tags;
  - declining the comparison without relating it to the viewer;
  - "may not match your mood", left in place without mentioning the runtime;
  - and twice, "not described as scary" for Pulp Fiction and Game of Thrones.
  With 5 titles per question in the blind sample, a 1-point gap is noise: Granite and Qwen are now
  tied.
- **Documents mode is worse** (90% against 96%). It cost cast and "fits" answers, and one answer took
  11.5 s. It is not adopted.
- **Speed is unchanged:** Granite typically answers in 0.6 s, and the checks cost nothing measurable.

**What this means for the default:** Granite 4.0 1B on the CPU stays the default. It ties Qwen3.5 2B on
quality, but it is 1.0 GB instead of 1.4 GB, the same on every platform, and 6× faster on the CPU. On a
Mac, Qwen3.5 2B on Metal is now an equally good choice.

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

- For "fits tonight", always answer with Flicks' own sentence when the code says no. The model's "may not
  match your mood" passes the check but leaves out the runtime.
- Build Flicks' own "why this pick" sentence from the reasons, as the narrator does, instead of letting the
  model list raw theme tags.
- If the blind gap stays, try LoRA fine-tuning on catalogue Q&A written by a larger teacher model (MLX on
  the M2, merged into one GGUF), measured against these two title sets.
- Retest Granite on Metal with a newer llama.cpp before treating CPU-only as permanent.
- Not tested: Gemma 4 E2B and Qwen3.5 4B (3 GB files, left out on this machine), Granite 4.0 H 1B (the
  hybrid version), and Inkling, which needs two data-centre GPUs and can't run locally.
