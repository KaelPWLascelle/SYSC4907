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
