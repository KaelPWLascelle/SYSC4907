# Test and measurement report (2026-10-21)

One run of everything that can be measured on the team's development machine, after the October
clean-up. It records what each figure is, the command that produces it, and what it means for the
architecture. Machine: Apple M2, 8 GB, macOS 26, Python 3.12, Node 24. Raw outputs are written to
`work/report/` (git-ignored) by the commands below.

## Summary

| Area | Result |
|---|---|
| Backend unit and integration tests | 272 passed, 3 skipped (optional voice packages), 345 subtests, 6.9 s |
| Interface unit tests (Vitest) | 89 passed in 20 files |
| Browser end-to-end (Playwright) | 19 passed (13 Chrome desktop, 3 phone, 3 Safari/WebKit), 25 s including the build |
| Lint, types, format | ruff, ESLint, `tsc` (app and test configs), Prettier: all clean; `npm audit`: 0 vulnerabilities |
| Recommendation latency | 0.1–0.4 ms on 36 titles; 13–62 ms median on 9,349 titles |
| HTTP latency | 1.3–1.8 ms on 36 titles; 2–57 ms median on 9,349 titles |
| Server memory | 233 MB peak with both catalogues loaded in one process (about 90 MB serving one) |
| Recommendation quality (MovieLens, 3 likes) | HR@10 0.108, coverage 0.038, personalisation 0.942; popularity alone 0.127 / 0.010 / 0.676 |
| Ask student | 16 / 30 exact on the held-out test set, 0.14 ms per request |
| Ask pipeline without a language model | 7 / 11 agent cases at 0.4 ms (the 4B model: 10 / 11 at 4.2 s) |
| Discover and "Pick for me" | 77 ms per feed page and 54 ms per pick on 9,349 titles; 65% of films have an embeddable trailer |

## Correctness

### Commands

```
python -m pytest -q
cd web && npm run lint && npm run typecheck && npx prettier --check src e2e && npx vitest run
cd web && npm run test:e2e
```

CI (`.github/workflows/flicks.yml`) runs the backend tests on Linux, Windows and macOS with Python
3.10 and 3.12, the interface checks and build, a packaging check, and now the Playwright suite.

### Browser end-to-end tests

`web/e2e/` drives the real server (bundled catalogue, a fresh temporary home folder) in Chromium. Every
test fails on any console error or Content Security Policy violation.

| Test | What it proves |
|---|---|
| Home | a top pick with its reasons, 12 picks, and the default scene sentence |
| Rating | a like shows at once, survives a reload, and clears on a second press |
| Scene sentence | changing the mood sends a new ranking request; extra controls stay behind "More options"; reset |
| Why this pick | the narrated reason matches the scene; the score parts add up to the total; the sheet fits its content |
| Ask | a described evening ("long week, … nothing scary") becomes mood relaxing, avoid horror, with no model server |
| Your taste | the chart reflects seeded ratings; a tuned mix reaches the ranking request |
| Request guard | a cross-site POST is refused (403) |
| Discover | a like in the feed is a rating; nothing is requested from YouTube until trailers are allowed, then only privacy-enhanced embeds |
| Pick for me | draws from the top 12 or from anything, and states the chance |
| Profiles | a PIN profile asks who is watching, refuses a wrong PIN, accepts the right one |
| Phone (Pixel 7) | home, pickers, Your taste, Why this pick and Discover never scroll sideways |
| Discover layout (Chrome and Safari's WebKit) | trailer and poster stay inside their space at three window shapes; added after Safari stretched the trailer past the card |

### Styling refactor check

The stylesheet split (`tokens.css`, `theme.css`, `taste.css`) was checked by snapshotting the computed
style of every element on each screen before and after and diffing them: 0 differences. A CSS cascade
layer version was tried and rejected because layers invert specificity (`h3` beat `.tile-title`).

## Performance

`python -m flicks.benchmark --out work/report/benchmark.json` times each stage in process and each
endpoint over HTTP (FastAPI test client, so no network), on fixed inputs, median and 95th percentile of
200 calls (50 over HTTP) after a warm-up.

| Stage (median / p95 ms) | 36 titles (content only) | 9,349 titles (content + collaborative) |
|---|---:|---:|
| Start-up (catalogue, TF-IDF, neighbours, database) | 38 | 839 |
| Recommend, no ratings | 0.11 / 0.12 | 13.0 / 49.9 |
| Recommend, 2 ratings | 0.20 / 0.20 | 54.8 / 92.1 |
| Recommend, 40 ratings | 0.36 / 0.37 | 61.8 / 102.2 |
| Explain one pick | 0.10 / 0.11 | 46.7 / 77.0 |
| Taste summary, 40 ratings | 0.44 / 0.45 | 62.7 / 107.8 |
| Search "funny films from the 90s" | 0.08 / 0.08 | 2.7 / 2.9 |
| Ask "long week, … nothing scary" | 0.26 / 0.27 | 0.70 / 0.71 |
| Ask "something like the martian but lighter" | 0.13 / 0.13 | 15.4 / 17.1 |
| `GET /api/state` | 1.5 / 1.8 | 1.5 / 1.7 |
| `POST /api/recommend` | 1.8 / 2.1 | 57.5 / 98.9 |
| `GET /api/titles?q=` | 1.3 / 1.4 | 4.9 / 5.1 |
| `POST /api/command/preview` | 1.6 / 2.1 | 2.0 / 2.1 |
| `GET /api/taste` | 1.6 / 1.8 | 55.8 / 94.2 |
| `POST /api/explain` | 1.3 / 1.4 | 46.2 / 48.7 |

**What it means.** Every interaction answers well inside the 100 ms that feels instant, on a laptop
with no GPU and no model server. The cost at MovieLens scale is scoring every title for every request
(linear in catalogue size); the explanation re-runs that scoring to place the pick, which is why it
costs nearly as much as a ranking. If the catalogue grows by another order of magnitude, the first
optimisations are caching the ranked list per scene for the explanation, and pruning candidates with
the collaborative neighbours before content scoring.

## Recommendation quality (MovieLens)

`python -m flicks.datasets.evaluation --out work/report/recommendation.json` (about 5 minutes). MovieLens
latest-small: 280 development users tune the blend and prior, 323 test users are scored. Each test user's
held-out likes are hidden, the model sees 3, 10 or all of the rest, and HR@10 is the share of users with a
held-out like in their top 10 out of the full catalogue (± is a 95% interval).

| Model (test users, HR@10 / NDCG@10) | 3 likes | 10 likes | Full history |
|---|---:|---:|---:|
| Random | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 |
| Popularity | 0.127 / 0.072 | 0.127 / 0.072 | 0.127 / 0.072 |
| Content (TF-IDF) | 0.015 / 0.010 | 0.031 / 0.026 | 0.025 / 0.020 |
| Collaborative (item-item) | 0.043 / 0.018 | 0.084 / 0.045 | 0.099 / 0.054 |
| Hybrid (blend 2.0) | 0.050 / 0.026 | 0.102 / 0.059 | 0.105 / 0.054 |
| Hybrid + prior 2.0 (best NDCG) | 0.136 / 0.078 | 0.133 / 0.082 | 0.108 / 0.058 |
| **Hybrid + prior 1.0 (shipped)** | **0.108 / 0.061** | **0.121 / 0.069** | **0.105 / 0.057** |

Beyond accuracy, top 10 with 3 likes (coverage: share of the catalogue shown to anyone; personalisation:
1 − overlap between users' lists; popularity percentile: 0 is the most popular title):

| Model | Coverage | Personalisation | Genre diversity | Popularity pct |
|---|---:|---:|---:|---:|
| Popularity | 0.010 | 0.676 | 0.789 | 0.001 |
| Content (TF-IDF) | 0.141 | 0.987 | 0.579 | 0.397 |
| Hybrid (blend 2.0) | 0.106 | 0.987 | 0.693 | 0.098 |
| Hybrid + prior 2.0 | 0.020 | 0.878 | 0.767 | 0.003 |
| **Hybrid + prior 1.0 (shipped)** | **0.038** | **0.942** | **0.754** | **0.009** |

**What it means.** On held-out accuracy alone, popularity is a hard baseline to beat on
MovieLens. The hybrid beats each of its parts, and only the popularity prior lifts
it past popularity; the strongest prior then gives every new user nearly the same blockbusters. Flicks
ships half that strength: it gives up about a fifth of the HR@10 with 3 likes for nearly twice the
coverage and clearly more personal lists, and the gap closes as a user rates more (0.105 against 0.108
with full history). The figures are identical to the run before the clean-up, so the refactor did not
change ranking. The reasoning is in [ADR 0009](adr/0009-popularity-prior.md) and
[ADR 0015](adr/0015-your-taste.md).

## AI components

### Ask student (`flicks/assistant/ask_student.py`)

`python -m flicks.datasets.ask --evaluate-only` scores the shipped weights (1.7 MB) without retraining.

| Set | Exact | Mood | Intensity | Novelty | Watch/listen | Avoid | Time per request |
|---|---:|---:|---:|---:|---:|---:|---:|
| Test (30, held out, no phrase shared with the training bank) | 16 / 30 | 0.67 | 0.97 | 0.97 | 1.00 | 0.93 | 0.14 ms |
| Dev (25, used to grow the bank, so optimistic) | 22 / 25 | 0.92 | 1.00 | 1.00 | 0.96 | 1.00 | 0.14 ms |

Mood is the weak head; most misses are abstentions, which leave the scene unchanged.

### The whole Ask pipeline against the language model

`python -m flicks.assistant.agent_eval --no-llm` sends the 11 agent cases (requests the rules alone cannot
read) through the shipped pipeline, rules then student, and scores them the same way as the model.

| Reader | Passed | Median latency | Memory |
|---|---:|---:|---|
| Rules + student (shipped) | 7 / 11 | 0.4 ms | inside the server |
| qwen3.5:4b agent (ADR 0013) | 10 / 11 | 4.2 s | about 4 GB; froze the 8 GB machine |
| qwen3.5:2b agent (ADR 0013) | 6 / 11 | 1.8 s | about 2 GB |

The shipped pipeline misses: a title described rather than named ("the guy stranded on mars"), a
described title read as a scene ("that slow alien language one"), "my heart pounding" read as mood tense
without raising intensity, and "what time is it in tokyo" turned into a title search. The first two need
world knowledge, which is what the optional language model adds; the last two are fixable in the rules.

### System One tagging and distillation (`flicks/tagging.py`, `flicks/distill.py`)

Scored against the team's editorial mood and intensity on the 36 bundled titles. The Laya rows are the
recorded run against a local System One server (2026-10-02); it was not re-run because loading it does
not fit alongside the server on an 8 GB machine.

| Teacher | Mood hit@1 | Mass on editorial mood | Calibration error | Intensity MAE | Latency per title |
|---|---:|---:|---:|---:|---:|
| Majority / constant baseline | 0.500 | – | – | 0.214 | – |
| Lexical stand-in (`python -m flicks.tagging`) | 0.667 | 0.556 | 0.183 | 0.201 | < 0.1 ms |
| Laya via System One (recorded) | 0.583 | 0.439 | 0.273 | 0.182 | 279 ms (p95 289) |

Student agreement with its teacher (`python -m flicks.distill --tags … --student …`), top-1 per decision:

| Teacher | Train | Dev | Test |
|---|---:|---:|---:|
| Lexical stand-in | 0.558 | 0.375 | 0.458 |
| Laya (recorded) | 0.904 | 0.688 | 0.875 |

**What it means.** On 36 titles neither teacher is clearly better than a word list, so tags stay an
offline, optional signal rather than a runtime dependency. The distilled student copies Laya far more
faithfully than it copies the word list, because Laya's judgements are consistent where the word list is
not; that is the argument for the teacher-student design once a larger tagged catalogue exists.

### Discover, Up next and "Pick for me" (added 21 October)

Built on branch `feat/discover` ([ADR 0016](adr/0016-discover.md)) and measured with the same benchmark:

| Stage (median / p95 ms) | 36 titles | 9,349 titles |
| --- | ---: | ---: |
| Discover page of 8 (40 ratings, 100 shown) | 0.42 / 0.49 | 77.4 / 117.6 |
| Pick for me (2 ratings) | 0.15 / 0.17 | 54.3 / 92.0 |
| `POST /api/discover` | 1.8 / 1.9 | 69.8 / 108.6 |
| `POST /api/pick` | 1.3 / 1.5 | 56.1 / 93.2 |

Trailer data (`python -m flicks.datasets.trailers --verify`): 8,443 of 9,349 MovieLens films matched the
MovieLens YouTube Trailers dataset, and 6,101 (65%) were still embeddable when checked with YouTube's
oEmbed endpoint (13 minutes, video IDs only); the bundled catalogue keeps 21 of 33 films.

## Clean-up in this pass

- **Assistant code in one package.** `commands`, `intent`, `voice`, `ask_student`, `agent`, `agent_eval`,
  `llm` and `narrator` moved into `flicks/assistant/`, so the top level is the recommender and the server.
- **One text folding.** `flicks/text.py` replaces two copies of the same normalisation; checked identical
  on 5,007 strings.
- **Dead code removed** (found with `vulture`, each checked by hand): an unused constant in the request
  guard, an unused factor list, and two repository merge methods superseded by the transactional
  profile import.
- **Stylesheets.** One token file, one theme, and the "Your taste" component in its own file.
- **Real benchmark.** `flicks/evaluate.py` (a 36-title timing demo) became `flicks/benchmark.py`.
- **Evaluation flags.** `--evaluate-only` on the Ask trainer and `--no-llm` on the agent check, so the
  shipped AI can be measured without retraining or a model server.
- **Browser tests in CI**, with traces uploaded on failure.

## Recommendations

1. **Merge the two Dependabot pull requests** (#24 Python, #25 web) after CI passes on them.
2. **Decide on `Trailer-Scroller---POC`**: it is 2 commits ahead and 4 behind `main`, and adds a separate
   1,700-line frontend. Port the idea into `web/src` or close the branch. `feat/ready-to-watch` is merged
   and can be deleted.
3. **Add coverage reporting** (`pytest-cov`, `@vitest/coverage-v8`) to CI, to show which code the 340
   tests leave untested.
4. **Fix the two rule gaps** the agent check found (intensity words, off-topic questions with nouns).
5. **Re-run the System One evaluation** on a machine with memory to spare, on a larger tagged catalogue.
