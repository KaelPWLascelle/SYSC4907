# Architecture

Flicks is a Python server and a React interface that run on the user's own machine. The server binds
to loopback, keeps all personal data in one SQLite file (one or more local profiles), and computes every
recommendation locally. Free-form requests are read by the Ask student, a small distilled classifier that
runs in process; an optional, experimental language model can be added on the same machine. Neither ranks.
The reasons behind each major choice are in the [decision records](adr/README.md).

```
┌──────────────────────────── this machine ────────────────────────────┐
│                                                                      │
│  Browser ──▶ host app (FastAPI, 127.0.0.1:8765)                      │
│                 │  request guard: Host/Origin, JSON-only, size, CSP  │
│                 ├─ routes/profiles   who is watching · export/import  │
│                 ├─ routes/library    recommender (core.py) · narrator │
│                 │                    ─────────────────────────────────┼──▶ local LLM server
│                 │                                                     │    (127.0.0.1, optional)
│                 ├─ routes/assistant  rules → System One → student → (LLM)
│                 ├─ routes/playback   files · relay · watch history ──┼──▶ Internet Archive
│                 │                                                     │    (only on Play)
│                 └─ routes/couch      CouchManager ─┐                 │
│                                                    ▼                 │
│                         SQLite (~/.flicks)   guest app (LAN, only    │
│                                              during a session)       │
└──────────────────────────────────────────────────────▲───────────────┘
                                                       │
                                       phones on the same Wi-Fi
```

## Components

### Backend (`flicks/`)

| Module | Responsibility |
|---|---|
| `__main__.py` | Command line: builds `Settings`, the services and the app, then runs uvicorn on loopback |
| `text.py` | The two text foldings every match uses: `normalize` (what people type) and `title_key` (titles and file names) |
| `config.py` | `Settings` and default paths (`~/.flicks/`) |
| `services.py` | Builds the long-lived objects (recommender, repositories, media library, couch manager) |
| `api/app.py` | The host app: middleware, error handlers, routers, and the built interface |
| `api/security.py` | The request guard shared by both apps (see [Security model](#security-model)) |
| `api/routes/` | One router per area (library, assistant, playback, couch); routes stay thin |
| `api/schemas.py` | Request bodies: strict types, no unknown fields; ranges are checked by the domain |
| `api/guest.py`, `api/server.py` | The couch guest app and its lifecycle in a background thread |
| `core.py` | Domain types (`Content`, `Session`), the TF-IDF taste model and the session reranker |
| `db.py`, `repositories.py` | SQLite connections, migrations, profiles, and per-profile ratings and watch history |
| `profiles.py`, `api/routes/profiles.py` | Profile sign-in (cookie tokens, PIN lockout) and the portable export/import document ([ADR 0012](adr/0012-local-profiles.md)) |
| `api/deps.py` | `viewer`: the request's profile, through which every route reads ratings and history |
| `assistant/llm.py` | Client for a local OpenAI-compatible model server; refuses non-loopback addresses ([ADR 0013](adr/0013-local-llm.md)) |
| `assistant/ask_student.py`, `datasets/ask.py` | The Ask student (a distilled classifier for described scenes), its phrase bank, training and evaluation ([ADR 0014](adr/0014-ask-student.md)) |
| `assistant/agent.py`, `assistant/agent_eval.py` | The optional language-model agent (after the student) and its evaluation |
| `assistant/narrator.py` | Grounded, cached plain-language explanations of a pick's factors (optional LLM) |
| `discover.py`, `trailers.py`, `datasets/trailers.py` | The Discover feed (three interleaved streams), "Pick for me", and the trailer index and its import ([ADR 0016](adr/0016-discover.md)) |
| `taste.py` | "Your taste": genre lean, tag themes and the liked films shaping picks, from the ranking's own data ([ADR 0015](adr/0015-your-taste.md)) |
| `media.py` | Maps local video files to catalogue titles |
| `relay.py`, `archive.py` | Remote media played through Flicks (Range forwarding, forced media type, sniffing), and the validated Internet Archive index ([ADR 0011](adr/0011-streaming.md)) |
| `assistant/commands.py`, `assistant/intent.py` | Rule-based command parsing (scene, ratings, play, search, similar titles), with an optional local System One fallback |
| `assistant/voice.py` | Optional on-device Whisper transcription with bounded audio decoding |
| `couch.py`, `qr.py` | Couch-session rules (joining, hidden votes, results, player state) and the QR encoder |
| `posters.py` | The one-time artwork fetch (Wikipedia page images in batches) and the read-only cache |
| `search.py` | In-memory lookup and everyday-language search: reads decades, years, lengths, kinds, genres and moods, then ranks word matches over titles, shows, genres, tags and descriptions ([ADR 0007](adr/0007-catalogue-artifact.md)) |
| `collaborative.py` | Item-to-item collaborative filtering, the content/collaborative blend and the popularity prior ([ADR 0008](adr/0008-collaborative-filtering.md), [0009](adr/0009-popularity-prior.md)) |
| `datasets/` | Build-time tools: the MovieLens, trailer and Internet Archive importers, neighbour precomputation, and the offline evaluation |
| `net.py` | Outbound HTTP for explicit, user-requested actions: posters, imports and streams; public addresses only |
| `systemone.py`, `tagging.py`, `distill.py` | System One client, catalogue tagging and the distilled student |

`core.py`, `couch.py` and `repositories.py` contain no HTTP code, so they are tested directly.

### Interface (`web/`)

React 19 and TypeScript, built by Vite into `flicks/static/` with two entry points: the host app
(`index.html`) and the couch phone page (`couch.html`).

| Path | Responsibility |
|---|---|
| `src/api/` | Typed client and response types mirroring the Python API |
| `src/host/App.tsx` | Owns the user's state (ratings, scene, open sheet, playback) and wires the screens |
| `src/host/components/` | Hero, rails and tiles, scene bar, Ask bar, details sheet, browse grid, couch panel, player |
| `src/host/hooks/` | Recommendations (debounced, aborting stale requests), history, couch host polling |
| `src/host/commands/` | `CommandController`: the voice and command state machine, framework-free |
| `src/host/library.ts`, `reasons.ts` | Shared title lookups and actions; plain-language reasons from score factors |
| `src/guest/` | The couch phone app and its polling hook |
| `src/lib/` | Formatting, polling that loads in background tabs, and the in-browser student model |

Server responses that can arrive out of order are guarded: recommendation requests abort their
predecessors, and couch polls that started before the user's own action are discarded.

## Data model

All personal data is in one SQLite file (default `~/.flicks/feedback.sqlite3`). Schema changes are
numbered migrations tracked with `PRAGMA user_version`; see [ADR 0003](adr/0003-sqlite-migrations.md).

| Table | Columns | Notes |
|---|---|---|
| `profiles` | `id`, `name` (unique, case-insensitive), `pin_hash` (scrypt, optional), `created_at` | Migration 3; profile 1 "Me" owns data from earlier versions |
| `feedback` | `profile_id`, `content_id`, `value` (1 or -1), `updated_at` | A missing row means no rating |
| `watch_history` | `profile_id`, `content_id`, `position_seconds`, `duration_seconds`, `completed`, `started_at`, `updated_at` | Finished at 90% watched; resumable from 30 s |

Timestamps are ISO 8601 UTC with milliseconds. Deleting a profile deletes its rows (foreign keys).

The catalogue is a validated, read-only JSON file, loaded once at startup: the bundled
`flicks/data/movies.json` or an imported one ([ADR 0007](adr/0007-catalogue-artifact.md)). The browser
never receives it whole; it searches it page by page through `/api/titles`.

## Security model

Everything here is enforced in code and covered by tests (`tests/test_flicks.py`, `test_couch.py`,
`test_playback.py`).

- **Loopback only.** The host app binds to `127.0.0.1` and answers only `Host: 127.0.0.1` or
  `localhost`, which defeats DNS rebinding.
- **No cross-site requests.** Any request carrying an `Origin` other than the app's own is refused.
  State-changing requests must be JSON, which forces a CORS preflight that is never approved.
- **Bounded input.** JSON bodies are capped at 8 KiB and audio at 5 MiB, including chunked uploads
  without a `Content-Length`. Request bodies are validated with strict types and no unknown fields.
- **Strict Content Security Policy.** Only the app's own scripts, styles, images and media load;
  no inline scripts. The one frame allowed is YouTube's privacy-enhanced embed, for Discover trailers
  the viewer has turned on (host app only; [ADR 0016](adr/0016-discover.md)).
- **No paths from requests.** Media and poster routes serve only files matched to a catalogue ID at
  startup.
- **No URLs from requests.** The running app fetches remote media only when the user presses Play,
  and only from the URL in an imported index (the Internet Archive); a request names only the title's
  ID. Only public http(s) addresses may be fetched, redirects included. Relayed responses always carry
  the expected video type with `nosniff`, and a file that does not start like video is refused. See
  [ADR 0011](adr/0011-streaming.md).
- **Couch guests are isolated.** They use a separate server with its own routes, so ratings, history,
  voice and commands are unreachable from the network. See [couch mode](couch.md).
- **User text stays local.** Typed or spoken requests may only go to a System One model or a language
  model on this machine; both clients refuse other addresses and bypass proxies. See
  [System One](system-one.md) and [ADR 0013](adr/0013-local-llm.md).
- **Profiles.** The sign-in cookie is a random token, HttpOnly and SameSite=Strict; PINs are salted scrypt
  hashes with a lockout after five wrong tries. A profile with a PIN is never the default. Profile
  imports are capped at 2 MiB and validated field by field.
- **Model output is untrusted.** The Ask agent can only propose what the rules can (validated like the
  manual controls, IDs only from its own lookups); the narrator's text is discarded if it names a title
  it was not given. Neither can change stored data.

The database is not encrypted, and any local OS user with access to the file can read it; a profile PIN
separates household members, it does not encrypt. Flicks is
not designed to be exposed beyond the machine (for example through a tunnel).

## Recommendation model

### Taste (TF-IDF)

Each title is represented by its genres (repeated 3 times), tags (2 times) and description, as
lowercase alphanumeric tokens with a small stop-word list. For count c of term t in document d:

```
TF(t,d)  = 1 + ln(c)
IDF(t)   = 1 + ln((N + 1) / (document_frequency(t) + 1))
x_d      = L2_normalize(TF · IDF)
p        = L2_normalize(Σ x_d over liked d)
n        = L2_normalize(Σ x_d over disliked d)
u        = L2_normalize(p − 0.7·n)
taste(d) = (cosine(x_d, u) + 1) / 2
```

With no ratings, taste is a neutral 0.5. Normalizing the positive and negative centroids separately
means the 0.7 weight sets the direction regardless of how many titles were disliked.

### Taste (collaborative, when neighbours are available)

For a catalogue with a neighbour file (built from public MovieLens ratings, see
[ADR 0008](adr/0008-collaborative-filtering.md)), each title's taste is blended with a collaborative
prediction from the user's ratings r_j ∈ {+1, −1} of the films j that list it as a neighbour:

```
prediction(i) = Σ sim(i,j)·r_j / Σ sim(i,j)        support(i) = Σ sim(i,j)
weight(i)     = support(i) / (support(i) + 2)
taste(i)      = weight(i)·(prediction(i) + 1)/2 + (1 − weight(i))·taste_tfidf(i)
```

Titles no rated film points to keep their TF-IDF taste. Similarity is adjusted cosine over co-raters,
shrunk by n/(n + 10), top 30 per film. Discovery still uses TF-IDF familiarity, because it measures
theme distance rather than preference. Recommendations name the liked films that contributed
(`because`).

### Popularity prior (when the neighbour file has popularity)

A new user has no ratings, so neither taste model knows anything about them. The neighbour file
also records how many MovieLens raters liked each film, and taste starts from that
([ADR 0009](adr/0009-popularity-prior.md)):

```
popularity(i) = log(1 + likes(i)) / log(1 + max likes)
w             = s / (s + number of likes and passes)
taste(i)      = w·popularity(i) + (1 − w)·taste_hybrid(i)
```

With no ratings, picks are the most widely liked films that fit the scene; each rating moves weight
to the user's own taste. A pick is marked `popular` when the prior supplied at least half of its
taste score, and only then does the interface call it a crowd favourite. The strength s is tuned
offline (docs/evaluation.md).

### Session reranking

Hard constraints come first and apply in both modes: rated titles, titles longer than the available
time, titles in an avoided genre and, with **Ready to play**, titles that cannot be played right now are removed. The rest are scored:

| Factor | Definition | Default weight |
|---|---|---:|
| Taste | The taste score above | 0.55 |
| Mood | 1 if the title has the requested mood, otherwise 0; "anything" gives 0.5 | 0.20 |
| Intensity | 1 − \|title intensity − requested intensity\| | 0.15 |
| Discovery | 1 − \|(1 − cosine(x_d, p)) − requested novelty\| | 0.10 |

The weights are the session's `mix`, which the user can tune in "Your taste"; it must be four non-negative
numbers summing to 1, so a score stays in [0, 1] and its factors still add up to it.

Without likes, discovery is a neutral 0.5. Results are sorted by score, then by content ID for
stability, and the top 12 are returned. The "taste only" lens ranks by taste alone. Scores are
ranking signals in [0, 1], not probabilities, and the factors shown in the interface add up to the
score exactly.

The weights are design choices, not learned values. Measuring whether they help is the subject of
the [evaluation plan](evaluation.md).

### Extension points

`Recommender` accepts any `TasteModel` (`scores(feedback)`) and any `DecisionLayer`
(`factors(content, taste, session)`). A decision layer must return finite, non-negative weighted
factors that sum to [0, 1]. `TaggedDecision` (System One tags) is one such layer. Hard constraints
stay in the application and cannot be overridden by a model.

## API

All responses are JSON unless noted. Errors have the shape `{"error": "<message>"}`.

### Host app (`127.0.0.1:8765`)

| Method and path | Purpose |
|---|---|
| `GET /api/state` | Catalogue size and genres, ratings, voice status, posters, couch mode, and every playable title (`remote` when it streams, with its `source` and `page`) |
| `GET /api/titles` | Search: `q` (everyday language), `show` (`all`, `liked`, `passed`, `unrated`), `similar` (an ID: titles like it), `offset`, `limit` (≤ 100). Most popular first without a query; `understood` lists what the query was read as |
| `POST /api/feedback` | `{"id": "m001", "value": 1}`: 1 like, -1 pass, 0 clear |
| `POST /api/recommend` | `{"session": {...}, "mode": "session" \| "baseline"}`; omitted fields use defaults |
| `POST /api/explain` | `{"id", "session"}`: the pick's factors in words from the local model, or `narration: null` |
| `GET /api/taste` | The profile's genre lean, tag themes and the liked films shaping its picks |
| `POST /api/discover` | `{"session", "seen" (≤ 300 IDs), "online", "limit" (≤ 20)}`: a page of the Discover feed, each item with its `stream`, `why` and `media` (`kind`: `file`, `stream` or none; `trailer`: a YouTube ID or none) |
| `POST /api/pick` | `{"session", "pool": "picks" \| "anything"}`: one title drawn at random, with its `chance` and the `pool` size |
| `GET /api/profiles` | Profiles (name, PIN or not, rating count), the current one, and whether it was chosen |
| `POST /api/profiles` | `{"name", "pin"?}`: create a profile and sign in to it |
| `POST /api/profiles/{id}/select` | `{"pin"?}`: sign in (403 wrong PIN, 429 after five) |
| `POST /api/profiles/signout` | `{}`: forget this browser's sign-in |
| `PUT /api/profiles/current` | `{"name"?, "pin"?, "current_pin"?}`: rename; set, change or remove (`null`) the PIN |
| `DELETE /api/profiles/current` | Delete the signed-in profile and its data (keeps at least one) |
| `DELETE /api/profiles/current/data` | Clear its ratings and watch history |
| `GET /api/profiles/current/export` | Download the profile as a `flicks-profile` JSON document |
| `POST /api/profiles/import?mode=new\|merge` | Raw JSON export (≤ 2 MiB): into a new profile, or merged (newer wins) |
| `POST /api/command/preview` | `{"text": "...", "session": {...}}`: what a request would change; no side effects |
| `POST /api/command/apply` | Same body; re-parses the text and applies it |
| `POST /api/transcribe` | Raw audio (≤ 5 MiB, ≤ 30 s) → transcript |
| `GET /api/history` | Watch progress, most recent first, with each title's details |
| `PUT /api/history/{id}` | `{"position_seconds": 120.5, "duration_seconds": 840}` |
| `DELETE /api/history/{id}` | Forget progress for a title |
| `GET /media/{id}` | Play a film: a local file, otherwise relayed from the Internet Archive; supports `Range` (206) and `HEAD`; 502 when the source fails |
| `GET /posters/{id}` | A cached poster image |
| `GET /api/couch`, `GET /api/couch/qr.svg` | Couch session view and QR code (absent with `--no-couch`) |
| `POST /api/couch/start`, `stop`, `reveal`, `player` | Couch session controls (absent with `--no-couch`) |

A session is `{"mood", "minutes", "intensity", "novelty", "excluded_genres", "playable", "mix"}`;
`playable` keeps only titles with a local file or a stream. Moods are `any`,
`relaxing`, `uplifting`, `curious`, `tense` and `reflective`; minutes are 1–600; intensity and novelty
are 0–1.

### Couch guest app (home network, during a session)

`GET /join` (the phone page), `GET /posters/{id}` (shortlisted titles only), `GET /api/couch/state`,
and `POST /api/couch/join`, `vote` and `remote`. Requests after joining carry the guest token in an
`X-Flicks-Guest` header.

### Status codes

| Code | Meaning |
|---|---|
| 400 | Invalid request body or values |
| 401 | Missing or wrong guest token (couch), or every profile has a PIN and none is signed in |
| 403 | Wrong `Host` or a cross-site `Origin` |
| 404 | Unknown route, title, poster or media file |
| 409 | Voice is busy with another transcription |
| 429 | Too many wrong PINs; try again in a minute |
| 410 | The couch session has ended |
| 413 | Request body too large |
| 415 | Wrong content type |
| 416 | Requested byte range is outside the file |
| 503 | Storage or voice unavailable, or the interface is not built |
