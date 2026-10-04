# 0001. Local-first: the user's data never leaves the device

**Status:** Accepted (records the principle the project was proposed on)

## Context
The proposal's core claim is a recommender that personalises without cloud processing. Judges and
users can only trust that claim if the architecture makes leaks structurally hard, not just unlikely.

## Decision
- The app server binds to loopback. Ratings, watch history, voice and typed requests stay on the device.
- Network access is limited to explicit, user-run commands that send public catalogue data only
  (poster fetch, optional catalogue tagging) and to opt-in couch mode on the home network.
- Code enforces the boundaries (Host/Origin checks, loopback-only System One for user text,
  a guest server that has no host routes), and tests pin them.

## Consequences
Any feature that needs other people's data (collaborative filtering) must use public datasets
precomputed at build time. Every new network path needs a test that proves what it can reach.
