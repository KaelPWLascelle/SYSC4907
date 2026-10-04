# Flicks v0.2 architecture

The browser sends feedback and explicitly selected session context to a loopback
Python server. The server loads the catalogue once, computes TF-IDF once, reads
feedback from SQLite per recommendation request, ranks eligible titles, and
returns additive explanations. Static assets are local; there are no outbound
requests, telemetry, CDN dependencies, remote models, or cloud accounts.

## Boundaries

- `core.py`: validated Content/Session types, `TasteModel` and `DecisionLayer`
  protocols, TF-IDF implementation, deterministic reranker, eligibility policy.
- `store.py`: parameterized SQLite queries, one connection/transaction per operation,
  upserted ratings with timestamps. One local profile per database file.
- `__main__.py`: loopback HTTP transport, input validation, bounded request size,
  host/origin checks, restrictive content policy, static route allowlist.
- `static/`: accessible native browser controls, text-only rendering of catalogue
  data, explicit loading/error/empty states, request sequencing against stale results.
- `data/`: offline demo fixture and replacement schema.
- `voice.py`: optional local Whisper speech adapter with bounded in-memory decoding.
- `commands.py`: side-effect-free interpretation of supported session/rating commands.
- `static/voice.js`: microphone/file capture, transcript editing, preview and apply.

See [voice architecture and setup](voice.md) for the optional speech dependencies.

The HTTP server is a development/demo server, not a deployment or authentication
solution. All local OS users who can access the database or service can access the
profile. SQLite is not encrypted. Do not expose it through a tunnel or bind it to
a LAN address without replacing the transport/security design.

## Reproducible baseline

Each item is represented by genres repeated 3 times, tags repeated 2 times, and
its description. Lowercase ASCII alphanumeric tokens are used with a small explicit
stop-word list. This English-focused tokenizer is a known limitation.
For count c of term t in document d:

```
TF(t,d) = 1 + ln(c)
IDF(t) = 1 + ln((N + 1) / (document_frequency(t) + 1))
x_d = L2_normalize(TF * IDF)
p = L2_normalize(sum(x_d for liked d))
n = L2_normalize(sum(x_d for disliked d))
u = L2_normalize(p - 0.7*n)
taste(d) = (cosine(x_d, u) + 1) / 2
```

Empty/cancelled profiles get neutral taste 0.5. The normalized positive and
negative centroids mean the 0.7 negative weight controls direction independently
of the number of dislikes. Dislike-only profiles still demote similar content.
No popularity or collaborative signals are available in this fixture.

## Separate session decision layer

First, exclude every rated item and every item exceeding the available minutes, and every item matching an excluded genre.
Both comparison modes use identical hard constraints. Equality fits the limit.
The session layer scores every remaining candidate (no approximate retrieval yet):

| Factor | Definition | Weight |
|---|---|---:|
| Taste | Baseline score above | 0.55 |
| Mood | 1 if editorial mood matches, otherwise 0; Any gives 0.5 | 0.20 |
| Intensity | 1 - abs(item intensity - requested intensity) | 0.15 |
| Novelty | 1 - abs((1 - cosine(x_d,p)) - requested novelty) | 0.10 |

Without likes, novelty is neutral 0.5. Novelty measures theme distance from liked
content, not whether a person has watched a film; these concepts must not be
conflated. Weights are initial design choices, not learned or validated values.
Results sort by total descending then stable content ID, returning at most 12.
Taste-only mode ranks by taste alone. Scores are not probabilities, and absolute
scores from the two modes are not directly comparable.

Explanations list actual weighted contributions, positive/negative profile terms,
mood annotations, editorial intensity, and the duration constraint. They are
computed from the ranker, not generated prose. Display rounding can introduce a
0.001 difference when manually adding the visible numbers.

## Extension contracts

Inject `TasteModel.scores(feedback)` or `DecisionLayer.factors(content,taste,session)`
into `Recommender`. A taste adapter supplies a mapping by stable content ID with
`taste` in [0,1], `familiarity` in [0,1] or None, `evidence` terms and optional
`negative_evidence`. A decision adapter returns named finite nonnegative weighted
contributions summing to [0,1]. These are trusted in-process interfaces, not an
untrusted model-output boundary. Add validation, deadlines, and heuristic fallback
before connecting model outputs. Application-owned exclusions remain in place.

A future Laya/Kev-like adapter should return bounded scores through that decision
contract. No availability, license, accuracy, or hardware compatibility of any
specific model is assumed or verified in this MVP. Benchmark before adoption.

Whisper now transcribes speech locally; the bounded command interpreter maps
transcripts to reviewed feedback/session operations. FunctionGemma could later
replace this interpreter. Ambiguous titles currently produce no action. Eye-tracking context should be an opt-in provider with timestamps,
confidence, expiry, and manual override; it must not silently replace user choices.
Cross-domain content can reuse Content IDs/kind but needs domain-specific features,
runtime conventions, and evaluation. Voice input is implemented; eye tracking is not.

## API

- `GET /api/state`: catalogue and saved feedback.
- `POST /api/feedback`: `{"id":"m001","value":1}`; 1 like, -1 dislike, 0 clear.
- `POST /api/recommend`: `{"session":{"mood":"curious","minutes":120,
  "intensity":0.5,"novelty":0.3},"mode":"session"}`; mode may be `baseline`.

Session omissions use defaults; unknown fields/IDs and invalid values return 400.
Requests must use JSON, at most 8192 bytes. Storage failures return 503.

Voice endpoints: `POST /api/transcribe` accepts raw audio (maximum 5 MiB / 30 seconds).
`POST /api/command/preview` and `/api/command/apply` accept `text` and the current
`session`. Preview has no side effects. Apply reparses the text and updates only
recognized settings or a validated title rating. See docs/voice.md for examples.
