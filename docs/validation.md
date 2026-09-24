# Validation and next iteration

## Verified locally (2026-09-23)

Environment: macOS, Python 3.12.1, Codex in-app browser. No third-party Python
packages installed. The application was started with a separate demo SQLite file.

- Automated suite: **18 tests passed**, including real HTTP server tests.
- Browser: catalogue loads, Like/Dislike save, rated titles disappear from picks,
  ratings remain after browser reload and Python server restart, a 10-minute
  session shows an actionable empty state, mood/intensity controls change picks,
  and expanded explanations show the actual weighted factors.
- A malformed Relaxing option was found during browser testing, corrected, and
  covered by a regression test ensuring every supported mood is selectable.
- Baseline/session comparison, search, and clearing demo ratings were exercised.
- The interface was visually inspected in the browser. Formal accessibility and
  cross-browser/mobile testing are still outstanding.
- Cross-platform CI is configured but was not executed locally. Only the local
  environment above is a completed platform verification.

`python3 -m kevin.evaluate` reruns a deterministic demonstration with likes for
Arrival/Moon, a dislike for Alien, a Relaxing mood, 120 minutes, intensity 0.2,
and novelty 0.3. One local run over 200 calls per mode measured:

| Measurement | Result |
|---|---:|
| Load catalogue + build TF-IDF | 0.989 ms |
| Baseline ranking median / p95 | 0.278 / 0.311 ms |
| Session ranking median / p95 | 0.285 / 0.338 ms |
| Time/rated-title constraint violations | 0 in both modes |

This measures in-process ranking on 36 items, excluding browser, HTTP and SQLite
latency. It does not establish performance on embedded hardware or large datasets.
Timing varies per run. Baseline top five: The Truman Show, Blade Runner, The Iron
Giant, 12 Angry Men, A Trip to the Moon. Session top five: WALL-E, Before Sunrise,
Paddington 2, Sherlock Jr., Paddington. This demonstrates that session context
changes ordering, **not** that those changes improve user satisfaction.

## Experimental and incomplete at v0.1

The catalogue is small and curated; metadata has not been independently audited.
Mood/intensity annotations and scoring weights are subjective. TF-IDF detects
lexical overlap, not deep semantics. Negative feedback can suppress a shared genre
(e.g. disliking Alien can suppress science-fiction as well as horror). There is no
calibration, learned personalization, exploration policy, exposure logging,
profile separation inside one database, recommendation diversity constraint,
watch history, playback, voice, eye tracking, or external model integration.
Scores are not confidence estimates. Session settings are not persisted.

The original README's >70% hit-rate objective has **not** been demonstrated.
No honest precision/recall/NDCG claim can be made without independent relevance
judgments. The test suite verifies software behavior, not recommendation quality.

## Recommended next iteration: measure the context benefit

1. Audit and expand to a licensed catalogue with hundreds of items, stable IDs,
   verified runtimes, provenance, and independent mood/intensity annotations.
2. Ask each participant for seed likes/dislikes, then collect held-out relevance
   judgments for several explicitly chosen sessions. Keep these separate from
   profile training data and avoid deriving ground truth from our own tags.
3. Compare baseline versus session ranking in randomized, blinded order, using
   the same eligible candidates. Measure preferred list, time-to-choice,
   precision@5, NDCG@5 (with graded judgments), catalogue coverage, and constraint
   violations. Report participant counts, uncertainty, and unjudged items.
4. Tune weights on development participants and reserve other participants for
   final evaluation. Add opt-in local exposure/judgment exports with consent.
5. Only then compare TF-IDF to local embeddings and replace the decision adapter
   with a lightweight model if it improves measured utility within latency,
   memory, privacy, and licensing constraints. Add voice/eye signals afterwards.

## Repeatable browser smoke checklist

Start with a fresh `--db` path. Verify zero ratings; like Arrival; dislike Alien;
reload and restart the server; verify both ratings remain. Select Relaxing,
intensity 20%, 120 minutes and generate. Inspect factor contributions. Switch to
Taste only and generate. Search for Arrival, clear its rating, and check it can
return to recommendations. Set 10 minutes and generate: no results. Clear search
and restore defaults. Check the browser console for unexpected errors.


## v0.2 voice validation (2026-09-23)

The voice iteration adds local Whisper transcription, microphone/file capture,
editable transcript review, typed command fallback, explicit preview/apply, and
hard genre exclusions. Recommendations still use the original TF-IDF baseline.

- **38 Python tests passed** with the optional voice environment, covering command
  parsing, exact-title/negation handling, preview without side effects, application,
  exclusions, missing models, audio decoding, silence and duration limits, and the
  original recommender/API tests. Without extras the decoder tests are skipped.
- **9 Node UI-state tests passed**, covering microphone denial, cancellation during
  permission/recording/transcription, releasing microphone tracks, file size limits,
  invalidating edited previews, unknown commands, and no automatic application.
- Browser checks: audio-file upload → real local inference → editable transcript →
  session preview → Apply → changed controls and shortlist. Also tested typed title
  ratings, preview editing, rejection of “like it”, and clearing the test rating.
- The new panel was visually inspected. Physical microphone recording and actual
  OS permission prompts were not exercised; the permission/capture state machine
  was tested with simulated devices, and real speech inference used generated audio.
- CI now also includes a Node 24 UI-state job and optional Python audio-decoding job.
  CI does not download model weights; remote CI results are not yet verified.

### Actual offline inference smoke test

Generated English speech using macOS's local `say` tool, then transcribed locally
with `HF_HUB_OFFLINE=1`, faster-whisper 1.2.1, CTranslate2 4.8.2, CPU int8, 4 threads,
beam size 3, and speech activity filtering. Base English model revision:
`3d3d5dee26484f91867d81cb899cfcf72b96be6c`.

| Spoken request | Duration | Base processing | Parsed outcome |
|---|---:|---:|---|
| Kevin, something relaxing under ninety minutes, low intensity, no horror | 4.73 s | 1.417 s (includes initial load) | Relaxing, 89-minute limit, intensity .2, exclude horror |
| Kevin, I liked Arrival | 1.64 s | .469 s | Like Arrival |
| Kevin, I did not like Alien | 2.12 s | .415 s | Dislike Alien |

Tiny English recognized the session and dislike requests but misheard “I liked
Arrival” as “I like to rival.” The parser rejected it without changing a rating.
A short title prompt improved that sample, but the complete catalogue prompt did
not, so no prompt-based vocabulary tuning is shipped. Base English passed these
three samples and is the default setup choice; Tiny remains an optional lighter
model. This tiny synthetic sample does not establish a general accuracy rate.

### What to test next

Collect consented, short real-microphone recordings from the team with varied
voices, accents, room noise, and film titles. Measure word error rate, exact command
match, rejection rate, correction burden, and end-to-end latency. Keep recordings
out of Git and make retention opt-in. Compare Base/Tiny and a future FunctionGemma
interpreter against these held-out commands. Do not remove transcript review until
errors and ambiguous requests are understood. General chat, wake words, playback,
eye tracking, and a learned session decision model remain future work.
