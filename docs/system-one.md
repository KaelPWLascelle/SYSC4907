# System One models in Flicks (MVP)

A System One model answers typed questions (`choice`, `score`, `noul` yes/no) about a piece of
text in one forward pass, returning calibrated probabilities instead of generated prose. Flicks
uses them in three places, all behind the same validated client (`flicks/systemone.py`):

| Where | What is asked | Text sent | Allowed backends |
|---|---|---|---|
| Build-time catalogue tagging (`flicks/tagging.py`) | mood, intensity, pace, family-friendly per title | Public fields only: title, year, genres, description | Any: laya-serve, Kev, or hosted Jev |
| Command fallback (`flicks/intent.py`) | requested mood, genres to avoid | What the user typed | **Loopback only**; enforced in code |
| Distilled student (`flicks/distill.py`, `static/student.js`) | the same tagging questions | Any | Runs in-process / in the browser |

```
TMDB-style public text ──> teacher (Laya / Kev / Jev) ──> tags.json ──> TaggedDecision (soft mood + intensity)
                                                     └──> Laya fine-tune JSONL (state, questions, gold)
                                                     └──> hashed-BoW student ──> student.json ──> student.js (browser)
user's typed request ──> rules first ──(only if nothing matched)──> local System One ──> Session validation
```

## Guarantees the code enforces

- **Model output is untrusted.** `parse_answers` rejects answers for unasked questions, invented
  options, wrong types, NaN/out-of-range values, and probabilities that do not sum to 1.
- **User text stays local.** `DecisionClient.decide(..., private=True)` raises `PrivacyError`
  before any request if the backend is not on 127.0.0.1/::1/localhost. The command assistant
  refuses a remote backend at startup. Loopback requests bypass `http(s)_proxy` so a proxy cannot
  relay user text off the machine. Plain `http` to a remote host is refused outright.
- **Rules win.** The model is consulted only when the deterministic rules matched nothing
  (`reason: "unrecognized"`). It never overrides a deliberate refusal such as “not relaxing”.
- **Low confidence changes nothing.** Mood needs ≥ 0.60 and genre exclusion ≥ 0.80.
  Everything still passes `Session` validation, and the UI still requires Preview → Apply.
- **The teacher never sees editorial labels.** `film_state` excludes moods and intensity so the
  fixture's annotations can act as a (small, team-written) gold set.
- **Tag files are checked on load.** Every probability must be a finite number in [0, 1] over
  exactly the question's options, so a hand-edited file cannot push scores outside [0, 1].
- **Same factor contract.** `TaggedDecision` keeps HeuristicDecision's factor names and weights,
  so scores stay in [0, 1] and explanations still add up. Untagged titles fall back.

## Run it

Everything below works offline with the lexical stand-in, which is deterministic keyword overlap
dressed in the wire format. It is **not a model**; it exists for CI and as a floor to beat.

```sh
python3 -m flicks.tagging --out work/tags.json                    # tag + evaluate
python3 -m flicks.distill --tags work/tags.json --export-laya work/laya-data --student work/student.json
python3 -m flicks --tags work/tags.json --system-one-url lexical  # try “something cozy and soothing”
```

With a real local model (needs a machine that can download from Hugging Face; the Laya package
also installs torch):

```sh
pip install "laya[serve]"
LAYA_MODELS=english laya-serve                                   # http://0.0.0.0:8000; bind LAYA_HOST=127.0.0.1
python3 -m flicks.tagging --url http://127.0.0.1:8000 --out work/tags-laya.json
python3 -m flicks --tags work/tags-laya.json --system-one-url http://127.0.0.1:8000
```

Hosted Jev is allowed for catalogue tagging only (public text). Keep the key out of shell history:

```sh
export TYPESAFE_API_KEY=...        # early-access key
python3 -m flicks.tagging --url https://api.typesafe.ai --api-key-env TYPESAFE_API_KEY --out work/tags-jev.json
```

## Results so far (36 titles, 2026-10-02)

Both columns come from the same commit (`a2469a7`), catalogue and questions, via
`python3 -m flicks.tagging [--url http://127.0.0.1:8000]`. Laya is zero-shot: no fine-tuning, no
prompt changes.

| Metric | Lexical stand-in | Laya `english`, zero-shot | Trivial baseline |
|---|---:|---:|---:|
| Titles tagged / failed | 36 / 0 | 36 / 0 | — |
| Mood hit@1 (top mood is one of the editorial moods) | **0.667** | 0.583 | 0.500 (always “uplifting”) |
| Probability mass on editorial moods | **0.556** | 0.439 | — |
| Mood ECE | **0.183** | 0.273 | — |
| Intensity MAE (0–1 scale) | 0.201 | **0.182** | 0.214 (always the mean) |
| Per-title latency, median / p95 (client side, 4 questions) | < 1 ms | 279 / 289 ms | — |
| Student teacher-agreement, test top-1 (24 decisions) | 0.458 | 0.875 | — |
| Relaxing + intensity 0.2: Mad Max: Fury Road rank | 4th | not in the 12 results | — |

Setup: Apple M2, 8 GB RAM, macOS 26.5.1. laya-serve on `127.0.0.1:8000`, torch device `mps`, no CPU
fallbacks. laya 0.3.24, torch 2.14.1, transformers 5.18.0, Python 3.12.1, checkpoint `english` at
revision `55cf4c4e`. The weights download (~0.8 GB) and model load took about 5 minutes on the first run.
Latency is measured over all 36 titles after one warm-up request, one request per title.

Honest reading: zero-shot Laya is **worse than the keyword stand-in on mood**. It has lower hit@1,
less mass on the editorial moods and worse calibration. It is underconfident: mean top-mood
confidence is 0.31 against 0.58 accuracy. It never picks “reflective” (Arrival, Moon and The Truman Show
all come out “relaxing”), and it calls Toy Story and Sherlock Jr. “tense”. It beats both the stand-in
and the constant on intensity, but partly by hugging the middle: its intensity range is 0.22–0.58,
while the editorial range is 0.10–1.00. Its family answers are unreliable: it rates A Quiet Place among its four
most family-friendly titles. This fixture has no editorial family labels, so that is not scored. The one place
it clearly helps the product is ranking: its tags drop Mad Max from a relaxing/low-intensity session.
The student's higher agreement says Laya's tags are easier to imitate (they are more uniform), not
that they are better; on 36 titles it says the pipeline works, not that the student is good. With 36 titles and team-written labels, none of these gaps is statistically
meaningful. Fine-tuning and a real gold set are what will tell.

End-to-end (Flicks with Laya tags and Laya as the command fallback):

- “something cozy and soothing tonight” → `mood: relaxing` (79%).
- “not relaxing” is still refused by the rules, and the model is not consulted.
- “I want something that makes me think” → no change: the model guessed relaxing at 58%, below the
  0.60 gate. The gate stopped a wrong answer.
- Every recommendation's factors sum to its score (12/12 with both tag files).

## What each file is for

- `flicks/systemone.py`: question builders, validation, wire parsing, `HttpBackend` (`/v1/systemone`,
  bearer auth, timeouts), `LexicalBackend`, `DecisionClient` with the privacy check, ECE.
- `flicks/tagging.py`: `FILM_QUESTIONS`, `tag_catalog`, tag-file load/validate, `evaluate`, `TaggedDecision`.
- `flicks/intent.py`: `SystemOneInterpreter`, rules-first fallback for free text.
- `flicks/distill.py`: stable 70/10/20 split by ID hash, Laya fine-tune export, soft-label softmax student.
- `flicks/static/student.js`: browser port of the student; `tests/student.test.mjs` checks parity
  with Python to 1e-9 using `tests/fixtures/student-parity.json`, including non-ASCII film-state
  objects (both sides serialise objects as compact JSON with real characters).

## Next steps (in order)

1. ~~Run Laya (`english`, zero-shot) as a teacher~~ (done 2026-10-02, see above). Run Jev if early
   access arrives and add its column.
2. Replace the fixture with a few thousand MovieLens titles joined to TMDB overviews, keeping
   the teacher's input to public text. Hand-label ~300 titles as a real gold set (not our tags).
3. Fine-tune Laya on the teacher's soft labels with the exported JSONL on Kaggle's free 2×T4
   (see Laya's `docs/finetune.md`), fit temperatures on `dev`, report accuracy/ECE on `test`.
4. Distil a small transformer student (ONNX, int8) and compare it to the hashed-BoW student on
   accuracy, size and latency on the low-end test tablet. Keep whichever wins.
5. Ablation for the report: NDCG@10 of the recommender with editorial vs teacher vs student tags.
6. Move the intent fallback to the in-browser student once the PWA exists; widen the intent
   schema (runtime buckets, audience) and keep rules-first plus confidence gates.
