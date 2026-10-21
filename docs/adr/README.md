# Architecture decision records

Short records of decisions that shape Flicks, why they were made, and what they cost. Each record
is immutable once accepted; a later record supersedes it rather than editing it.

| # | Decision | Status |
|---|---|---|
| [0001](0001-local-first.md) | Local-first: the user's data never leaves the device | Accepted |
| [0002](0002-fastapi-backend.md) | FastAPI + uvicorn replace the standard-library HTTP server | Accepted |
| [0003](0003-sqlite-migrations.md) | SQLite stays; schema changes go through numbered migrations | Accepted |
| [0004](0004-react-vite-frontend.md) | React + TypeScript + Vite for the frontend, not Next.js | Accepted |
| [0005](0005-video-playback.md) | Direct play over HTTP range requests; transcoding is optional | Accepted |
| [0006](0006-installable-app.md) | Installable web app (manifest), no service worker | Accepted |
| [0007](0007-catalogue-artifact.md) | The catalogue is a read-only build artifact, searched in memory | Accepted · amends 0003 |
| [0008](0008-collaborative-filtering.md) | Item-to-item collaborative filtering, precomputed from public ratings | Accepted |
| [0009](0009-popularity-prior.md) | New users start from a popularity prior that gives way as they rate | Accepted |
| [0010](0010-podcasts.md) | Podcast episodes from public feeds, downloaded only when the user asks | Superseded by 0017 |
| [0011](0011-streaming.md) | Stream remote media through Flicks; public-domain films from the Internet Archive | Accepted · amends 0010 |
| [0012](0012-local-profiles.md) | Local profiles; a profile's data moves as a file, never through an account | Accepted · amends 0003 |
| [0013](0013-local-llm.md) | An optional local language model: an Ask agent and narrated explanations, never the ranker | Superseded at runtime by 0014 |
| [0014](0014-ask-student.md) | A distilled Ask student replaces the language model at runtime | Accepted |
| [0015](0015-your-taste.md) | "Your taste": a view of the profile, a tunable mix, and quality beyond accuracy | Accepted · amends 0009 |
| [0016](0016-discover.md) | Discover, Up next and "Pick for me": finding a film without searching | Accepted |
| [0017](0017-films-only.md) | Films only: podcasts removed; couch mode on by default | Accepted · supersedes 0010 |
