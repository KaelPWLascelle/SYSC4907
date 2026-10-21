# 0014. A distilled Ask student replaces the language model at runtime

**Status:** Accepted · supersedes the runtime role of [0013](0013-local-llm.md), which is now optional and off by default

## Context
ADR 0013 added a local language model as a third Ask tier. On the team's 8 GB Apple M2 it was unusable:
Ollama loaded the 4B model with its vision projector, could not fit it in GPU memory, disabled mmap and
pushed macOS into swap; the whole computer froze, and Ask requests took 5 to 20 seconds when it worked.
Most of what the agent did was read a described scene ("long week, I want to switch off, nothing scary")
into the scene bar's settings, which is a classification problem, not a generation problem.

## Decision
- **A tiny classifier does the reading** (`flicks/assistant/ask_student.py`). Five heads (mood, intensity, novelty,
  watch or listen, a genre to avoid), each a softmax regression over hashed word unigrams, bigrams,
  5-letter prefixes and letter 4-grams (8,192 features). Inference is pure Python: no NumPy, no model
  server. Weights are a 1.7 MB JSON file shipped in the package.
- **It is distilled from a teacher, offline.** The training requests are generated from a labelled phrase
  bank (`flicks/datasets/ask.py`) written with a language model's help on public phrasing only, the same
  teacher-student pattern as System One tagging. Training takes about 10 seconds with NumPy, which is a
  build-time extra.
- **Same guarantees as every Ask reader.** Rules run first and win, including deliberate refusals such as
  "not relaxing". The student fills in only what the rules could not read, answers only at ≥ 60%
  confidence, and its proposal passes `Session` validation and waits for Preview → Apply. A cue word
  followed by a catalogue title ("something like The Martian but lighter") becomes a "titles like" search.
- **Template explanations replace the narrator.** "Why this pick" builds its sentence from the pick's
  own factors in the interface (`explanation()` in `web/src/host/reasons.ts`): instant, and it can only
  say what the ranking used.
- **The language model stays available but off.** `--llm-url` still enables ADR 0013's agent and narrator
  after the student, for machines with memory to spare. The default model is now the 2B.

## Evaluation
Hand-written requests, scored per setting and as an exact match on all five (`python -m flicks.datasets.ask`):

| Set | Exact | Mood | Intensity | Novelty | Watch/listen | Avoid |
|---|---:|---:|---:|---:|---:|---:|
| Test (30, written after the model was final; no phrase shared with the bank) | 16 / 30 | 0.67 | 0.97 | 0.97 | 1.00 | 0.93 |
| Dev (25, used to grow the bank, so optimistic) | 22 / 25 | 0.92 | 1.00 | 1.00 | 0.96 | 1.00 |

Most test misses are abstentions (nothing changes, the rules' answer stands); three are a wrong mood,
which the preview shows before anything applies. Latency is about 0.2 ms in process and 4 to 40 ms over
HTTP; the Flicks server uses about 90 MB in total with the 9,762-title catalogue.

**Negative results, kept for the report.** A static-embedding model (`minishlab/potion-base-8M`, 8M
parameters) with the same heads scored 11 / 25 on the dev set, and nearest-phrase matching on its
embeddings 9 / 25: averaged word vectors lose the phrase meaning. A 4B language model scored 10 / 11 on an
easier set but froze the machine.

## Alternatives considered
- **A smaller language model (0.5 to 2B):** still gigabytes while loaded, seconds per request, and the 2B
  passed only 6 of 11 agent cases (ADR 0013).
- **A small transformer encoder (MiniLM, 22M parameters) with these heads:** likely more accurate on
  unseen phrasing, but needs PyTorch or ONNX Runtime at runtime (hundreds of MB). The natural next step if
  the mood head needs to improve: distil it into the same JSON heads at build time.

## Consequences
- Unseen vocabulary ("squeamish", "curveball") is the student's weak spot; each one fixed is a bank phrase,
  and the test set must then be replaced, not reused.
- `python -m flicks.datasets.ask` rebuilds the weights and prints the evaluation; a test fails if the test
  set ever shares a phrase with the bank.
