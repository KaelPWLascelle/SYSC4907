# 0002. FastAPI + uvicorn replace the standard-library HTTP server

**Status:** Accepted · supersedes the "zero third-party dependencies" constraint of the MVP

## Context
The MVP used `http.server` so it could run with no installs. Video playback needs HTTP range
requests (seeking), streaming responses and concurrent long-lived connections. Hand-writing those on
`http.server` would mean maintaining our own HTTP stack. Request validation was also hand-rolled per
route.

## Decision
Use FastAPI on uvicorn for the host app and the couch guest app.
- Starlette's `FileResponse` provides range requests; pydantic models validate request bodies.
- The JSON API contract (`{"error": "..."}` bodies, status codes) is preserved, so clients and tests
  carry over.
- Security behaviour is preserved and centralised in middleware: Host allow-list (DNS rebinding),
  Origin check and JSON-only bodies for state-changing requests (CSRF), body-size limits, and
  security headers (CSP, nosniff, no-store for API responses).
- Runtime dependencies: `fastapi`, `uvicorn`. Nothing else.

## Alternatives considered
- **Keep `http.server` and add range support by hand:** small now, but it grows with every feature
  (streaming, WebSockets) and we would own the bugs.
- **Flask:** synchronous by default and weaker typing; FastAPI is already used by `laya-serve`.

## Consequences
`pip install` is now required (two packages). Couch push updates over WebSockets become possible
later; polling stays for now because it is simple and adequate for up to 8 phones.
