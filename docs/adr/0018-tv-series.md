# 0018. TV series: a show is one title, ranked beside films

**Status:** Accepted · amends [0009](0009-popularity-prior.md) and [0017](0017-films-only.md)

## Context
People choosing what to watch together often settle on a series. ADR 0017 removed podcasts because
episodes made every layer handle a second kind of title: per-show caps in the picks, alternating
media, separate scoring outside the popularity prior, an audio player and downloads. It asked for TV
series to get their own decision for the same reason: a show has seasons and episodes, and watching
one is a run of evenings rather than one.

Two public sources cover what a film catalogue has:
- **TVmaze** (free API, no key; CC BY-SA): show summaries, genres, typical episode length, premiere
  and end dates, network, seasons and episode counts, cover images (hotlinking and caching allowed),
  and IMDb IDs. No ratings or popularity.
- **IMDb non-commercial datasets** (personal and non-commercial use): ratings and vote counts per
  title, but no plots or images.

## Decision
- **The unit is the show, not the episode.** A series is one catalogue title (`kind: "series"`)
  with a `series` record: seasons, episodes, the year it ended (none while it runs), network,
  TVmaze page and IMDb votes. Its `minutes` is one episode's typical length, so the scene's time
  limit reads naturally ("45 minutes" fits an episode). Liking a show rates the show. Nothing in the
  ranking needs per-show caps or alternation, because a show appears once.
- **Import is a command, like MovieLens** (`python -m flicks.datasets.tvmaze`). It pages through
  TVmaze's show index, keeps scripted, animated and documentary shows with a summary, a cover, a
  runtime, a known genre and an IMDb ID, joins IMDb's vote counts, and writes the most-voted
  1,000 to `~/.flicks/catalogs/series.json`, with an artwork index and a provenance file beside it.
  Genres map to the film vocabulary (Science-Fiction → science-fiction, Children → family, Anime →
  animation, Espionage → thriller, Supernatural → fantasy); the rest (legal, medical, history…)
  become tags. Moods and intensity are estimated from genres, as for films (`datasets/genres.py`).
- **Series load beside any film catalogue** (`--series`, by default `series.json` when present).
  IDs are `tv` plus the TVmaze ID, so they never collide with film IDs; a clash is refused.
- **The scene can ask for films, series or either** (`Session.kind`: `any`, `films`, `series`), a
  hard constraint like the time limit. The choice appears only when series are loaded. Search reads
  "series", "TV shows" and "sitcoms" (and "films" once series are loaded), and Ask reads "a show",
  "something to binge" or "a film".
- **One ranking, with popularity on each kind's own scale.** Taste is the same TF-IDF model for both
  kinds, and genres share one vocabulary, so a liked crime drama raises crime series too. The
  collaborative model stays film-only (MovieLens has no series). The popularity prior (ADR 0009)
  log-scales each kind's evidence separately (MovieLens likes for films, IMDb votes for series), so
  the most-voted show counts as much as the most-liked film. The prior runs only when the film
  catalogue has popularity; otherwise series alone would have it and crowd out the films.
- **Series are not played yet.** They are browsed, rated, searched, shortlisted in couch mode and
  explained like films, but "Ready to play" leaves them out, and local video files are matched to
  films only. Playing a show means choosing an episode and remembering progress through it, which
  needs per-episode history; that is left for a later decision.
- **Credit and licences.** The details sheet names the network and links the show's TVmaze page,
  which is where its description comes from (CC BY-SA). Covers go into the same local poster cache
  as film posters (`python -m flicks.posters`) and stay out of git. TVmaze offers them at 210 px or
  full size (about 680 px, 400 KB), so the fetch shrinks the original to the films' 330 px with
  Pillow (the `datasets` extra) and keeps the cache about the films' size per title. IMDb data is used for
  non-commercial research, as MovieLens is.

## Alternatives considered
- **Episodes as titles:** what podcasts did. It brings back per-show caps and floods the picks with
  one show's episodes, for a choice people make at the level of the show.
- **A separate Series screen:** keeps the rankings apart, but splits Home, Discover, Ask and couch
  votes in two, and a household deciding what to watch tonight wants both in one list.
- **IMDb alone:** it has the shows and ratings, but no descriptions or images, so the content model
  and the interface would have nothing to show.
- **Popularity on one scale** (IMDb votes beside MovieLens likes): votes are in the millions and
  likes in the hundreds, so every series would outrank every film for a new user.

## Consequences
- **Series reuse every layer** except the player: one ranking path, one poster style, one details
  sheet with a few more lines. The code added is mostly the importer.
- **Cross-kind ranking is not evaluated.** The offline evaluation uses MovieLens, which has no
  series; how films and series compare in one list is a question for the user study.
- **Weaker taste for series.** Without collaborative neighbours, a show's taste comes from its
  genres, tags and summary only, and estimated moods are coarser than for films.
- **The import makes about 1,350 requests** (show index pages, then each kept show's seasons) at
  TVmaze's rate limit, and caches them, so a re-run is quick.
