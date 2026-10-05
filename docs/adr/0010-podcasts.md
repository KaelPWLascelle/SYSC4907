# 0010. Podcast episodes from public feeds, downloaded only when the user asks

**Status:** Accepted · amends [0001](0001-local-first.md)

## Context
Flicks recommends something good for the time and mood you have, and long-form podcasts fit that as
well as films do ("something curious for my 50-minute walk"). Podcasts are published as public RSS
feeds, so any podcast app may fetch and play them. ADR 0001 limits network access to explicit,
user-run commands; playing a podcast needs its audio, which lives on the publisher's servers.

## Decision
- **Import is a command, like MovieLens** (`python -m flicks.datasets.podcasts`). It reads the feeds,
  keeps the newest long-form episodes (20 minutes to 10 hours, 50 per show), and writes a catalogue
  of episodes (`kind: "episode"`, with the show as `series`) plus an index of each episode's audio
  URL. Genres come from Apple Podcasts categories; moods and intensity are estimated from them, as
  for films. Only feed URLs are requested.
- **The running app may make one kind of remote request: downloading an episode the user pressed
  Download for** (`flicks/podcasts.py`). This amends ADR 0001. It sends nothing about the user beyond
  the request itself, which any podcast app sends. The URL comes from the imported index, never from
  the request; redirects may not leave http(s); the file is capped at 1 GiB, written under the
  episode's ID, and kept only if its first bytes are MP3, AAC, M4A or Ogg audio. One download runs at
  a time.
- **Playback reuses the local player.** A downloaded episode is served like a local video (range
  requests, resume, couch remote), with an audio layout. Nothing streams from the publisher.
- **Episodes are titles like films.** They are ranked by the same models; the scene adds a
  watch / listen / either choice as a hard constraint. At most two episodes of one show appear in
  the picks, since a show's episodes share genres and moods.
- **Behave like a podcast app, not a re-host.** Episodes are never altered, re-encoded or shared;
  downloads stay in `~/.flicks/podcasts`, out of git. The details sheet names the show and links to
  its page.

## Alternatives considered
- **Stream from the publisher in the browser:** simplest, but every play would contact the publisher
  and its analytics, the Content Security Policy would have to allow remote media, and nothing would
  work offline.
- **A command-line sync that downloads the newest episodes of every show:** keeps ADR 0001 unamended,
  but fills the disk with episodes nobody chose and cannot download the one a recommendation just
  surfaced.
- **A podcast directory API (Podcast Index, Apple):** better discovery, but needs an API key and
  sends searches to a third party. A curated feed list is enough for now.

## Consequences
- **A download reveals the user's IP address** and the episode to the publisher and its analytics
  services, as with any podcast app. The interface says episodes are downloaded only on request.
- **Feeds are untrusted input.** They are parsed with the standard library's XML parser (no external
  entities), capped at 40 MB, and validated before anything is written.
- **No collaborative signal for podcasts.** There is no public podcast ratings dataset, so episodes
  are ranked by the content model and the scene only. Without any ratings, a show's episodes tie.
- **Artwork is not imported yet;** episodes show generated title cards.
