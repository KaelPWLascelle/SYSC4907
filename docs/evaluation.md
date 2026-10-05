# Evaluation

This page separates what has been verified (the software does what it says) from what has not been
measured yet (whether the recommendations are good), and sets out how to measure it.

## What is verified

### Automated tests

| Suite | Count | Covers |
|---|---:|---|
| Backend (`pytest`) | 123 | Ranking and explanations, hard constraints, validation, migrations, the request guard, range-request streaming, watch history, posters, couch rules and the guest server over a real socket, command parsing, System One validation, catalogue search, and the MovieLens importer (offline fixtures) |
| Interface (Vitest) | 40 | The voice and command state machine (cancellation, stale results, permissions), couch phone flows, the player, the couch panel, server-side browsing, and the main screens |

Regression tests for bugs found during manual testing (a stale poll overwriting a vote, a background
tab not loading the couch session) were each checked to fail with the bug reintroduced. CI runs the
backend tests on Linux, Windows and macOS with Python 3.10 and 3.12, plus lint, the interface build,
and a packaging check.

### End to end, in a browser

Checked with a real WebM file and the built interface:

- playback streams with seeking (HTTP 206 range responses);
- pausing saves progress, closing with Escape saves first, and "Continue watching" resumes at the
  saved position;
- a phone choosing a title in couch mode opens and plays it on the TV, a pause from the phone pauses
  the TV, and the TV reports its own play and stop back to the phones;
- the phone page works at 375 px wide with no horizontal scrolling;
- no console errors or Content Security Policy violations.

A real phone joined a couch session over home Wi-Fi by hand. Recording from a physical microphone
has not been tested yet; the recording state machine is tested with simulated devices.

## Ranking demonstration

`python -m flicks.evaluate` runs a fixed profile (likes for *Arrival* and *Moon*, a dislike for
*Alien*) with a relaxing mood, 120 minutes, intensity 0.2 and novelty 0.3. Measured on an Apple M2
with Python 3.12 over 200 calls per mode:

| Measurement | Result |
|---|---:|
| Load catalogue and build TF-IDF | 0.90 ms |
| Taste-only ranking, median / p95 | 0.29 / 0.33 ms |
| Taste + scene ranking, median / p95 | 0.29 / 0.33 ms |
| Constraint violations (time, rated titles) | 0 in both modes |

Top five, taste only: *The Truman Show*, *Blade Runner*, *The Iron Giant*, *12 Angry Men*,
*A Trip to the Moon*. Top five with the scene: *WALL-E*, *Before Sunrise*, *Paddington 2*,
*Sherlock Jr.*, *Paddington*.

This shows that the scene changes the ordering and that ranking is fast on 36 titles in process
(excluding HTTP and SQLite). It does **not** show that the changes make people happier with the
picks.

## At MovieLens scale

The MovieLens import (`python -m flicks.datasets.movielens`, run 2026-10-05) produced **9,349 titles**
from 9,742: 268 were skipped for having no runtime on Wikidata, 87 for not being on Wikidata, 26 for
having no genres, and 12 for having no year. Measured on an Apple M2 with Python 3.12:

| Measurement | Result |
|---|---:|
| Load catalogue / build TF-IDF / build search index | 56 / 240 / 25 ms |
| Recommendations, cold start (median / p95) | 9 / 12 ms |
| Recommendations with 4 ratings (median / p95) | 51 / 56 ms |
| Search (`/api/titles`) | 3 ms in process; 6 ms for a 48-title page over HTTP |
| `/api/state` | 520 bytes (it previously embedded the catalogue, which would be 5.1 MB) |

Recommendations were 99 and 156 ms before taste evidence was limited to the titles returned. Output
is byte-for-byte identical across both catalogues, several profiles and scenes, and both lenses.

**What the content model gets wrong at this scale.** After liking *Star Wars* IV and V, the top picks
are *The Star Wars Holiday Special*, *Spaceballs*, *Ewoks: The Battle for Endor*, *Spaced Invaders*
and *Space Buddies*. TF-IDF matches shared words in the descriptions ("star", "wars", "space"), not
what people who liked those films go on to enjoy. This is the case for adding collaborative
filtering from MovieLens ratings, and for evaluating it against held-out ratings.

## Speech recognition smoke test

English speech generated with macOS's `say`, transcribed offline (`HF_HUB_OFFLINE=1`) with
faster-whisper 1.2.1 and CTranslate2 4.8.2 on CPU (int8, 4 threads, beam size 3), Base English model
revision `3d3d5dee26484f91867d81cb899cfcf72b96be6c`:

| Spoken request | Audio | Processing | Result |
|---|---:|---:|---|
| "Flicks, something relaxing under ninety minutes, low intensity, no horror" | 4.73 s | 1.42 s (includes model load) | Relaxing, 89-minute limit, intensity 20%, avoid horror |
| "Flicks, I liked Arrival" | 1.64 s | 0.47 s | Like *Arrival* |
| "Flicks, I did not like Alien" | 2.12 s | 0.42 s | Dislike *Alien* |

The smaller Tiny model misheard "I liked Arrival" as "I like to rival"; the parser rejected it
without changing a rating, which is the intended failure mode. Base is the default. Three synthetic
samples do not establish an accuracy rate.

## Limitations

- **The bundled catalogue is small and curated** (36 titles, subjective mood and intensity labels).
  The MovieLens catalogue is large, but its moods and intensity are estimated from genres.
- **TF-IDF captures word overlap, not meaning.** Disliking one film can suppress a whole shared
  genre (disliking *Alien* also pushes down other science fiction).
- **The weights are not learned or tuned,** and scores are not calibrated confidences.
- **No relevance judgments exist yet,** so no honest precision, recall or NDCG figure can be
  reported. The proposal's target of a hit rate above 70% has **not** been demonstrated.
- **Collaborative filtering is not implemented.** It is planned using public data (see below).

## Evaluation plan

1. **Catalogue.** Done for MovieLens latest-small (9,349 titles, with source, checksum, license and
   skip reasons recorded in the provenance file). Next: replace genre-estimated moods with System One
   tags and a hand-labelled sample.
2. **Relevance judgments.** Ask each participant for seed likes and dislikes, then collect held-out
   judgments for several chosen scenes. Keep judgments separate from training data, and never derive
   ground truth from the system's own tags.
3. **Taste only vs taste + scene.** Show both lists in randomized, blinded order over the same
   candidates. Measure the preferred list, time to choose, precision@5, NDCG@5 (graded), coverage
   and constraint violations. Report participant counts and uncertainty.
4. **Tuning.** Tune weights on development participants only and report final results on others.
5. **Model comparisons.** Only then compare TF-IDF with local embeddings, item-to-item collaborative
   filtering precomputed from public ratings, and System One tags, within latency, memory and privacy
   limits.
6. **Speech.** Collect consented recordings from the team (varied voices, accents and noise). Measure
   word error rate, exact command match, rejection rate and latency. Keep recordings out of git.

## Repeatable manual checklist

Start Flicks with a fresh `--db`. Like *Arrival* and pass on *Alien*; reload and restart, and check
both ratings remain. Choose Relaxing, intensity 20% and 2 hours, and open a title's "why this pick"
sheet to inspect the factors. Switch the lens to taste only. Set 10 minutes and check the empty
state. With `--media`, play a title, pause, close, and resume from "Continue watching". Check the
browser console for errors.
