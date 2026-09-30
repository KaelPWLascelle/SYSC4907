# System One models in Kevin (MVP)

A System One model answers typed questions (`choice`, `score`, `noul` yes/no) about a piece of
text in one forward pass, returning calibrated probabilities instead of generated prose. Kevin
uses them in three places, all behind the same validated client (`kevin/systemone.py`):

| Where | What is asked | Text sent | Allowed backends |
|---|---|---|---|
| Build-time catalogue tagging (`kevin/tagging.py`) | mood, intensity, pace, family-friendly per title | Public fields only: title, year, genres, description | Any: laya-serve, Kev, or hosted Jev |
| Command fallback (`kevin/intent.py`) | requested mood, genres to avoid | What the user typed | **Loopback only**; enforced in code |
| Distilled student (`kevin/distill.py`, `static/student.js`) | the same tagging questions | Any | Runs in-process / in the browser |

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
python3 -m kevin.tagging --out work/tags.json                    # tag + evaluate
python3 -m kevin.distill --tags work/tags.json --export-laya work/laya-data --student work/student.json
python3 -m kevin --tags work/tags.json --system-one-url lexical  # try “something cozy and soothing”
```

With a real local model (needs a machine that can download from Hugging Face; the Laya package
also installs torch):

```sh
pip install "laya[serve]"
LAYA_MODELS=english laya-serve                                   # http://0.0.0.0:8000; bind LAYA_HOST=127.0.0.1
python3 -m kevin.tagging --url http://127.0.0.1:8000 --out work/tags-laya.json
python3 -m kevin --tags work/tags-laya.json --system-one-url http://127.0.0.1:8000
```

Hosted Jev is allowed for catalogue tagging only (public text). Keep the key out of shell history:

```sh
export TYPESAFE_API_KEY=...        # early-access key
python3 -m kevin.tagging --url https://api.typesafe.ai --api-key-env TYPESAFE_API_KEY --out work/tags-jev.json
```

## Results so far (lexical stand-in, 36 titles, 2026-09-30)

| Metric | Lexical stand-in | Trivial baseline |
|---|---:|---:|
| Mood hit@1 (top mood is one of the editorial moods) | 0.667 | 0.500 (always “uplifting”) |
| Probability mass on editorial moods | 0.556 | — |
| Mood ECE | 0.183 | — |
| Intensity MAE (0–1 scale) | 0.201 | 0.214 (always the mean) |

Honest reading: the stand-in barely beats a constant on intensity, and with its tags a
relaxing/low-intensity session still ranks Mad Max: Fury Road fourth. That is the gap a real
teacher has to close, and these same commands will measure it. No real model has been run yet:
this environment could not reach Hugging Face. The student's teacher agreement on 36 titles
(test top-1 0.458) says the pipeline works, not that the student is good.

## What each file is for

- `kevin/systemone.py`: question builders, validation, wire parsing, `HttpBackend` (`/v1/systemone`,
  bearer auth, timeouts), `LexicalBackend`, `DecisionClient` with the privacy check, ECE.
- `kevin/tagging.py`: `FILM_QUESTIONS`, `tag_catalog`, tag-file load/validate, `evaluate`, `TaggedDecision`.
- `kevin/intent.py`: `SystemOneInterpreter`, rules-first fallback for free text.
- `kevin/distill.py`: stable 70/10/20 split by ID hash, Laya fine-tune export, soft-label softmax student.
- `kevin/static/student.js`: browser port of the student; `tests/student.test.mjs` checks parity
  with Python to 1e-9 using `tests/fixtures/student-parity.json`, including non-ASCII film-state
  objects (both sides serialise objects as compact JSON with real characters).

## Next steps (in order)

1. Run Laya (`english`, zero-shot) and, if early access arrives, Jev as teachers on this catalogue;
   commit both reports next to the lexical one. Expect weak zero-shot Laya (published 0.36).
2. Replace the fixture with a few thousand MovieLens titles joined to TMDB overviews, keeping
   the teacher's input to public text. Hand-label ~300 titles as a real gold set (not our tags).
3. Fine-tune Laya on the teacher's soft labels with the exported JSONL on Kaggle's free 2×T4
   (see Laya's `docs/finetune.md`), fit temperatures on `dev`, report accuracy/ECE on `test`.
4. Distil a small transformer student (ONNX, int8) and compare it to the hashed-BoW student on
   accuracy, size and latency on the low-end test tablet. Keep whichever wins.
5. Ablation for the report: NDCG@10 of the recommender with editorial vs teacher vs student tags.
6. Move the intent fallback to the in-browser student once the PWA exists; widen the intent
   schema (runtime buckets, audience) and keep rules-first plus confidence gates.
