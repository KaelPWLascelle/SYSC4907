# 0004. React + TypeScript + Vite for the frontend, not Next.js

**Status:** Accepted

## Context
The UI is about to grow several times over (player, continue watching, library, settings, couch).
Hand-built DOM code is hard to share across a team, and its tests needed a hand-written fake DOM.
The team knows React from Next.js.

## Decision
- React 19 + TypeScript (strict) built with Vite into `flicks/static/`, which the Python app serves.
  Two entry points: the host app (`index.html`) and the couch guest page (`couch.html`).
- **Not Next.js:** its strengths (server rendering, routing on a Node server) do not apply to a client
  app talking to a local Python API, and it would add a second server process.
- Vitest + Testing Library for component and hook tests; ESLint (typescript-eslint, react-hooks).
- Build output is not committed. CI builds it before Python tests and packaging; developers run
  `npm run build` once, or `npm run dev` with Vite proxying the API.
- No UI framework or state library: React state and a few hooks are enough at this size.

## Consequences
Developers need Node 20+ to change the UI; users of a built package do not. The strict CSP
(`script-src 'self'`) still holds because Vite emits external module scripts only.
