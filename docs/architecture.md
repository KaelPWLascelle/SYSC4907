# Architecture

Flicks is a Python server and a React interface that run on the user's own machine. The server binds
to loopback, keeps all personal data in one SQLite file, and computes every recommendation locally.
The reasons behind each major choice are in the [decision records](adr/README.md).

```
┌──────────────────────────── this machine ────────────────────────────┐
│                                                                      │
│  Browser ──▶ host app (FastAPI, 127.0.0.1:8765)                      │
│                 │  request guard: Host/Origin, JSON-only, size, CSP  │
│                 ├─ routes/library    recommender (core.py)           │
│                 ├─ routes/assistant  commands · intent · voice       │
│                 ├─ routes/playback   files · relay · watch history ──┼──▶ podcast publishers,
│                 ├─ routes/podcasts   episode downloads ──────────────┼──▶ Internet Archive (only
│                 └─ routes/couch      CouchManager ─┐                 │    on Play or Download)
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
| `config.py` | `Settings` and default paths (`~/.flicks/`) |
| `services.py` | Builds the long-lived objects (recommender, repositories, media library, couch manager) |
| `api/app.py` | The host app: middleware, error handlers, routers, and the built interface |
| `api/security.py` | The request guard shared by both apps (see [Security model](#security-model)) |
| `api/routes/` | One router per area (library, assistant, playback, couch); routes stay thin |
| `api/schemas.py` | Request bodies: strict types, no unknown fields; ranges are checked by the domain |
| `api/guest.py`, `api/server.py` | The couch guest app and its lifecycle in a background thread |
| `core.py` | Domain types (`Content`, `Session`), the TF-IDF taste model and the session reranker |
| `db.py`, `repositories.py` | SQLite connections, migrations, ratings and watch history |
| `media.py` | Maps local video files to catalogue titles |
| `podcasts.py` | Podcast episodes at runtime: the validated episode index, downloads (one at a time, sniffed as audio) and downloaded files ([ADR 0010](adr/0010-podcasts.md)) |
| `relay.py`, `archive.py` | Remote media played through Flicks (Range forwarding, forced media type, sniffing), and the validated Internet Archive index ([ADR 0011](adr/0011-streaming.md)) |
| `commands.py`, `intent.py` | Rule-based command parsing (scene, ratings, play, search, similar titles), with an optional local System One fallback |
| `voice.py` | Optional on-device Whisper transcription with bounded audio decoding |
| `couch.py`, `qr.py` | Couch-session rules (joining, hidden votes, results, player state) and the QR encoder |
| `posters.py` | The one-time artwork fetch (Wikipedia page images in batches, podcast show art) and the read-only cache |
| `search.py` | In-memory lookup and everyday-language search: reads decades, years, lengths, kinds, genres and moods, then ranks word matches over titles, shows, genres, tags and descriptions ([ADR 0007](adr/0007-catalogue-artifact.md)) |
| `collaborative.py` | Item-to-item collaborative filtering, the content/collaborative blend and the popularity prior ([ADR 0008](adr/0008-collaborative-filtering.md), [0009](adr/0009-popularity-prior.md)) |
| `datasets/` | Build-time tools: the MovieLens, podcast and Internet Archive importers, neighbour precomputation, and the offline evaluation |
| `net.py` | Outbound HTTP for explicit, user-requested actions: posters, imports, streams and downloads; public addresses only |
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
| `src/host/hooks/` | Recommendations (debounced, aborting stale requests), history, podcast downloads, couch host polling |
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
| `feedback` | `content_id`, `value` (1 or -1), `updated_at` | A missing row means no rating |
| `watch_history` | `content_id`, `position_seconds`, `duration_seconds`, `completed`, `started_at`, `updated_at` | Finished at 90% watched; resumable from 30 s |

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
  no inline scripts.
- **No paths from requests.** Media and poster routes serve only files matched to a catalogue ID at
  startup, or episodes downloaded under their ID.
- **No URLs from requests.** The running app fetches remote media only when the user presses Play
  or Download, and only from the URL in an imported index (a podcast feed or the Internet Archive);
  a request names only the title's ID. Only public http(s) addresses may be fetched, redirects
  included. Relayed responses always carry the expected audio or video type with `nosniff`, and a
  file that does not start like audio or video is refused; downloads are capped at 1 GiB. See
  [ADR 0010](adr/0010-podcasts.md) and [ADR 0011](adr/0011-streaming.md).
- **Couch guests are isolated.** They use a separate server with its own routes, so ratings, history,
  voice and commands are unreachable from the network. See [couch mode](couch.md).
- **User text stays local.** Typed or spoken requests may only go to a System One model on this
  machine. See [System One](system-one.md).

The database is not encrypted, and any local OS user with access to the file can read it. Flicks is
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
to the user's own taste. The prior covers only the film catalogue the ratings describe; podcast episodes
keep their own taste, since no data is not the same as unpopular. A pick is marked `popular` when the prior supplied at least half of its
taste score, and only then does the interface call it a crowd favourite. The strength s is tuned
offline (docs/evaluation.md).

### Session reranking

Hard constraints come first and apply in both modes: rated titles, titles longer than the available
time, titles in an avoided genre, and titles of the wrong medium (watch or listen, when podcasts are
loaded) are removed. The rest are scored:

| Factor | Definition | Weight |
|---|---|---:|
| Taste | The taste score above | 0.55 |
| Mood | 1 if the title has the requested mood, otherwise 0; "anything" gives 0.5 | 0.20 |
| Intensity | 1 − \|title intensity − requested intensity\| | 0.15 |
| Discovery | 1 − \|(1 − cosine(x_d, p)) − requested novelty\| | 0.10 |

Without likes, discovery is a neutral 0.5. Results are sorted by score, then by content ID for
stability, and the top 12 are returned, with at most two episodes of any one podcast (a show's
episodes share genres and moods, so they would otherwise fill the row). In "either" mode the best
films and the best episodes alternate, led by whichever scores higher: their scores rest on different
evidence (public popularity and collaborative patterns exist for films only), so they are compared
within each medium rather than across. The "taste only" lens ranks by taste alone. Scores are
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
| `POST /api/command/preview` | `{"text": "...", "session": {...}}`: what a request would change; no side effects |
| `POST /api/command/apply` | Same body; re-parses the text and applies it |
| `POST /api/transcribe` | Raw audio (≤ 5 MiB, ≤ 30 s) → transcript |
| `GET /api/history` | Watch progress, most recent first, with each title's details |
| `PUT /api/history/{id}` | `{"position_seconds": 120.5, "duration_seconds": 840}` |
| `DELETE /api/history/{id}` | Forget progress for a title |
| `GET /media/{id}` | Play a title: a local file or downloaded episode, otherwise relayed from its source (episodes, Archive films); supports `Range` (206) and `HEAD`; 502 when the source fails |
| `GET /posters/{id}` | A cached poster image |
| `GET /api/podcasts/downloads` | Downloaded, downloading, queued and failed episodes (with a podcast catalogue) |
| `GET /api/podcasts/{id}` | An episode's show, its page and its download status |
| `POST /api/podcasts/{id}/download` | `{}`: download the episode from its feed's audio URL (202) |
| `DELETE /api/podcasts/{id}/download` | Delete a downloaded episode or forget a failed download (409 while downloading) |
| `GET /api/couch`, `GET /api/couch/qr.svg` | Couch session view and QR code (with `--couch`) |
| `POST /api/couch/start`, `stop`, `reveal`, `player` | Couch session controls (with `--couch`) |

A session is `{"mood", "minutes", "intensity", "novelty", "excluded_genres", "medium"}`; medium is
`any`, `watch` or `listen`. Moods are `any`,
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
| 401 | Missing or wrong guest token (couch) |
| 403 | Wrong `Host` or a cross-site `Origin` |
| 404 | Unknown route, title, poster or media file |
| 409 | Voice is busy with another transcription, or an episode is still downloading |
| 410 | The couch session has ended |
| 413 | Request body too large |
| 415 | Wrong content type |
| 416 | Requested byte range is outside the file |
| 503 | Storage or voice unavailable, or the interface is not built |
