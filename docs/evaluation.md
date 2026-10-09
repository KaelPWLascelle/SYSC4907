# Evaluation

This page separates what has been verified (the software does what it says) from what has not been
measured yet (whether the recommendations are good), and sets out how to measure it.

## What is verified

### Automated tests

| Suite | Count | Covers |
|---|---:|---|
| Backend (`pytest`) | 192 | Ranking and explanations, hard constraints, validation, migrations, the request guard, range-request streaming, watch history, posters, couch rules and the guest server over a real socket, command parsing (scene, ratings, play, search, similar titles), System One validation, everyday-language search, the MovieLens and podcast importers (offline fixtures), podcast downloads and the streaming relay (with a fake network), the Internet Archive importer and its rights rule, collaborative filtering (neighbour build, predictions, blend, leakage-free evaluation split) and the popularity prior |
| Interface (Vitest) | 54 | The voice and command state machine (cancellation, stale results, permissions), couch phone flows, the player (video and audio), the couch panel, server-side browsing, streaming and podcast downloads, and the main screens |

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

## Recommendation quality on MovieLens

`python -m flicks.datasets.evaluation` (2026-10-05) measures how well each model finds a film a user
actually liked, using held-out MovieLens ratings:

- **Who is evaluated:** 603 MovieLens
  users with at least 5 liked catalogue films (rating ≥ 4.0).
- **What is held out:** one liked film per user, chosen with a fixed seed. Ratings ≥ 4 become likes
  and ≤ 2 become passes; anything in between is ignored, since Flicks has no neutral rating.
- **What is measured:** each model ranks every catalogue film the user has not rated. **HR@10** is
  how often the held-out film lands in the top 10; **NDCG@10** also rewards a higher position.
- **No leakage:** neighbours are rebuilt from the ratings minus every held-out rating.
- **Development and test users:** users are split in half by a hash of their ID. The blend strength
  is chosen on the development half only; every number below is from the test half.
- **New users too:** each model is also evaluated with only 3 or 10 of a user's likes, because
  Flicks' own users start with few. The blend is tuned for the mean over these profile sizes
  (mean NDCG@10 by strength: 0.25: 0.0480, 0.5: 0.0496, 1.0: 0.0514, 2.0: 0.0530, 4.0: 0.0516, 8.0: 0.0450, 16.0: 0.0359, 32.0: 0.0287; chosen: 2.0).
- **Popularity prior:** its strength is then tuned the same way, on top of the chosen blend (mean
  NDCG@10 by strength: 0.125: 0.0551, 0.25: 0.0564, 0.5: 0.0595, 1.0: 0.0646, 2.0: 0.0685, 4.0: 0.0681,
  8.0: 0.0676, 16.0: 0.0684; chosen: 2.0, the smallest of a flat top). Popularity is counted from the
  training ratings only, like the neighbours.
- **Sampled HR@10** ranks the held-out film among 100 random unrated films. It is common in the
  literature but optimistic (Krichene & Rendle, 2020), so the full-catalogue figures are the ones
  to quote.

**Test users, 3 likes** (323 users)

| Model | HR@10 (95% CI) | NDCG@10 | HR@10, sampled |
|---|---:|---:|---:|
| random | 0.000 ± 0.000 | 0.000 | 0.074 |
| popularity | 0.127 ± 0.036 | 0.072 | 0.771 |
| content (TF-IDF) | 0.015 ± 0.013 | 0.010 | 0.257 |
| collaborative (item-item) | 0.043 ± 0.022 | 0.018 | 0.158 |
| hybrid (blend 2.0) | 0.050 ± 0.024 | 0.026 | 0.359 |
| **hybrid + popularity prior (2.0)** | **0.136 ± 0.037** | **0.078** | 0.786 |

**Test users, 10 likes** (323 users)

| Model | HR@10 (95% CI) | NDCG@10 | HR@10, sampled |
|---|---:|---:|---:|
| random | 0.000 ± 0.000 | 0.000 | 0.074 |
| popularity | 0.127 ± 0.036 | 0.072 | 0.771 |
| content (TF-IDF) | 0.031 ± 0.019 | 0.026 | 0.313 |
| collaborative (item-item) | 0.084 ± 0.030 | 0.045 | 0.406 |
| hybrid (blend 2.0) | 0.102 ± 0.033 | 0.059 | 0.564 |
| **hybrid + popularity prior (2.0)** | **0.133 ± 0.037** | **0.082** | 0.811 |

**Test users, full history** (323 users)

| Model | HR@10 (95% CI) | NDCG@10 | HR@10, sampled |
|---|---:|---:|---:|
| random | 0.000 ± 0.000 | 0.000 | 0.074 |
| popularity | 0.127 ± 0.036 | 0.072 | 0.771 |
| content (TF-IDF) | 0.025 ± 0.017 | 0.020 | 0.353 |
| collaborative (item-item) | 0.099 ± 0.033 | 0.054 | 0.650 |
| hybrid (blend 2.0) | 0.105 ± 0.034 | 0.054 | 0.681 |
| **hybrid + popularity prior (2.0)** | **0.108 ± 0.034** | **0.058** | 0.746 |

**Reading the results.**
- **Collaborative filtering roughly triples or quadruples quality.** At every profile size, the
  hybrid is 3–4× better than the content model alone: HR@10 0.105 against 0.025 with full histories,
  and 0.050 against 0.015 for a new user with 3 likes.
- **Popularity is a strong baseline,** as is common on MovieLens: held-out liked films skew popular.
  Without the prior, popularity clearly beats the hybrid for new users (0.127 against 0.050 with 3
  likes).
- **The popularity prior closes that gap.** Starting from popularity and giving way to the user's
  own taste as they rate (ADR 0009) nearly triples the hybrid's hit rate with 3 likes (0.136 against
  0.050) and raises it with 10 likes (0.133 against 0.102). It now matches or edges past popularity
  at 3 and 10 likes, though within the margin of error, while staying personal: the list changes with
  every rating. With full histories the prior has little weight and popularity remains slightly
  ahead (0.127 against 0.108, also within the margin).
- **On the proposal's "hit rate above 70%" target:** on the sampled protocol the hybrid with the
  prior reaches 0.75 to 0.81, depending on the profile size, and popularity 0.77. On the full
  catalogue, the stricter and more honest measure, no model is near 70%. The target needs to be
  stated with a protocol before it can be claimed.

## Streaming start-up (informal spot check)

The proposal targets playback latency under 2 seconds. On 2026-10-08, over a home connection, through
the relay (`/media/{id}`), with a handful of requests each:

| Title | First bytes | Seek |
|---|---:|---:|
| *The General* (1926), Internet Archive, 640×480 MP4 | 1.4 s | 1.0–1.3 s typical; one seek near the end took 7 s |
| *In Our Time* episode, publisher's CDN | 3.1 s (several tracking redirects) | about 1 s |

Local files start well under a second. Remote start-up depends on the source and the network, so the
target can be claimed for local and downloaded media but not for every stream. A proper measurement
(time from pressing Play to the first frame, repeated, on the demo hardware) is still to do.

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
- **Offline measures are proxies.** Held-out MovieLens ratings show which model finds films people
  liked, not whether Flicks' users are happier with their picks; that still needs the user study below.

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
5. **Model comparisons.** Done offline for content, collaborative and hybrid models and the
   popularity prior (above). Next: local embeddings and System One tags, with the same protocol.
6. **Speech.** Collect consented recordings from the team (varied voices, accents and noise). Measure
   word error rate, exact command match, rejection rate and latency. Keep recordings out of git.

## Repeatable manual checklist

Start Flicks with a fresh `--db`. Like *Arrival* and pass on *Alien*; reload and restart, and check
both ratings remain. Choose Relaxing, intensity 20% and 2 hours, and open a title's "why this pick"
sheet to inspect the factors. Switch the lens to taste only. Set 10 minutes and check the empty
state. With `--media`, play a title, pause, close, and resume from "Continue watching". Check the
browser console for errors.
