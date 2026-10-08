# 0011. Stream remote media through Flicks; add public-domain films from the Internet Archive

**Status:** Accepted · amends [0010](0010-podcasts.md)

## Context
ADR 0010 made podcast episodes playable only after a download, which is slow for a 3-hour episode
and fills the disk with files nobody chose to keep. Separately, almost none of the catalogue's films
can be played, which undercuts the core of the proposal (a streaming player with recommendations).
The Internet Archive hosts thousands of public-domain films as plain MP4 files, and MovieLens lists
some of them.

## Decision
- **Play streams through Flicks** (`flicks/relay.py`). The browser asks Flicks for `/media/{id}`;
  Flicks fetches the media from where it lives and passes it on chunk by chunk, forwarding the
  browser's single `Range` header so seeking works. Download stays, as "Download for offline".
- **The relay keeps the security model of ADR 0010:**
  - the URL comes from an imported index, never from the request;
  - only public http(s) addresses may be fetched, including every redirect (no `localhost`,
    private networks, link-local or cloud metadata addresses), in `flicks/net.py`;
  - the response is always labelled with the expected audio or video type and `nosniff`, whatever
    the remote server says, so a hostile server cannot get a page rendered on Flicks' origin;
  - when the response starts at byte 0, its first bytes must be MP3, AAC, M4A or Ogg audio, or
    MP4 or WebM video;
  - the Content Security Policy is unchanged: the browser still loads media from Flicks only.
- **Public-domain films come from the Internet Archive** (`python -m flicks.datasets.archive`). Its
  feature-film collection is matched to the catalogue by title and year. Uploaders' own licence
  labels are ignored, because the collection also holds copyrighted uploads. A film is used only if
  it is public domain in the United States, where the Archive operates:
  - by **age:** released at least 96 years ago, or
  - by being **listed:** it appears in Wikipedia's "List of films in the public domain in the United
    States"; the revision used is recorded in the output.
  Colourised versions, trailers, clips and dubs are skipped, and the chosen file must be a
  browser-playable MP4 at least 60% of the film's runtime.
- **Credit the source.** Each streamed title names where it comes from ("In Our Time", "Internet
  Archive") and links to its page there.

## Alternatives considered
- **Point the browser at the remote URL** (`<video src="https://archive.org/...">`): less code, but the
  Content Security Policy would have to allow media from anywhere, and the browser would talk to
  third parties directly.
- **Trust the Archive's licence labels:** they are set by uploaders; *Dracula* (1931), still under
  US copyright until 2027, is labelled public domain there.
- **YouTube:** its terms forbid downloading or relaying videos, so it could only be an embedded
  player that talks to Google directly. It is left for a separate, opt-in decision.

## Consequences
- **Streaming needs the internet** and reveals the user's IP address and the title to the source,
  like any streaming app. Downloaded episodes and local files still play offline.
- **64 MovieLens films** can now be streamed (silent classics, *Night of the Living Dead*, *Detour*,
  *My Man Godfrey* and others); 333 Archive matches were refused as not known to be public domain.
- **Public domain is judged for the United States.** Other countries' terms differ (Canada's included),
  and a film's elements (a score, a restoration) can still be protected; the README says so.
- **Start-up and seek times depend on the source:** about 1–3 s in testing, longer when the Archive
  is slow.
