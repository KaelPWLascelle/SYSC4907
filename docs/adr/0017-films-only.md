# 0017. Films only: podcasts removed

**Status:** Accepted · supersedes [0010](0010-podcasts.md); amends [0011](0011-streaming.md) and [0014](0014-ask-student.md)

## Context
Podcast episodes were added as a second medium ([ADR 0010](0010-podcasts.md)): a "Watch or listen" choice
in the scene, episodes in the picks, audio playback and offline downloads. In use, the team found they
did not fit what Flicks is for, choosing a film to watch together. They also cost more than they gave:
- **A second kind of title everywhere.** Square artwork, show names instead of years, at most two
  episodes per show in a row, films and episodes alternating in "either" mode, an audio player, a
  download manager.
- **Separate scoring.** Public ratings exist for films only, so episodes were exempt from the
  popularity prior and compared only with each other.
- **Ask was harder.** The Ask student needed a watch-or-listen head, and the rules a "listen" verb.

## Decision
- **Flicks recommends and plays films only.** The podcast catalogue, importer, downloads, routes,
  audio player, episode artwork and the scene's "Watch or listen" choice are removed, as is
  `Session.medium`.
- **The relay stays** for public-domain films on the Internet Archive, now video only.
- **The Ask student is retrained without the watch-or-listen head** (8,000 generated requests, up from
  6,000, chosen on the dev set). The rules now read "not too long" or "something short" as 90 minutes.
- **Couch mode is on by default** (separate change, same release). It was hidden behind `--couch`.
  Nothing listens on the network until the host starts a session, so offering it costs no exposure;
  `--no-couch` hides it.

## Evaluation
| Measure | Before | After |
|---|---|---|
| Ask student, held-out test set (30) | 16 / 30 exact; mood 0.67 | 18 / 30 exact; mood 0.70, intensity 1.00, novelty 0.97, avoid 0.93 |
| Ask student, dev set (25) | 22 / 25 | 22 / 25 |
| Rules + student on the agent's hard cases | 7 / 11 | 6 / 10 (0.4 ms) |
| Ask student weights | 1.7 MB | 1.4 MB |

The test labels changed with the task (no watch-or-listen labels), so the two rows are not a strict
comparison. Two of the earlier agent-case passes came only from the removed setting ("to listen to",
"to watch").

## Consequences
- About 1,200 lines of code and 600 lines of tests are gone. One kind of title means one ranking path,
  one player and one poster style.
- A podcast catalogue built earlier (`~/.flicks/catalogs/podcasts.json`) is ignored, and downloaded
  episodes in `~/.flicks/podcasts` can be deleted by hand.
- If TV series are added later, they need their own decision: a show is a different unit from a film
  (seasons, episodes, progress through a series), as podcasts were.
