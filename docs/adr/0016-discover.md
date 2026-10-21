# 0016. Discover, Up next and "Pick for me": finding a film without searching

**Status:** Accepted · rebuilds the `Trailer-Scroller---POC` branch inside Flicks

## Context
The proposal promised three discovery features beyond Home and Browse: a vertical trailer feed,
continuous play, and a random pick. A teammate's proof of concept showed the feed was worth having: a
snap-scrolling, one-film-per-screen feed is quick to react to. But it was a separate application with
its own server, database and interface. It fetched popular films from TMDB with a personal API token
and downloaded the trailers with yt-dlp, which YouTube's terms forbid, and it needed a manually copied
ffmpeg on Windows. Its feed was sorted by title, and likes went to their own table, so reacting changed
nothing. It saved playback progress on every `timeupdate` event, several requests a second.

## Decision
- **Discover is part of Flicks** (`flicks/discover.py`, `POST /api/discover`, `Discover.tsx`). A like or a
  pass in the feed is an ordinary rating, so it shapes the next page, Home, and every other list.
- **Three streams, interleaved** (for you, for you, new, wildcard, for you, new): the scene's own
  ranking; the same ranking with discovery turned up; and the best film in genres the profile has
  neither rated nor been shown. Every card says which stream it came from and why. Rated and
  already-shown titles are skipped, so each reaction reshapes what follows.
- **Offline first.** A card plays a silent preview of the film itself when Flicks can play it (a local
  file or a public-domain stream), from a tenth of the way in. Otherwise it shows the poster and
  description. Discover works with no connection.
- **Trailers are opt-in and never downloaded.** `python -m flicks.datasets.trailers` matches the catalogue
  to the MovieLens 20M YouTube Trailers dataset (GroupLens, keyed by MovieLens ID; no API key) and stores
  video IDs only. The interface embeds a trailer only after the viewer allows it, explaining what YouTube
  will see. It uses YouTube's privacy-enhanced domain and only on the card in view. The Content Security
  Policy allows frames from that one origin, on the host app only. The page still sends no Referer; the
  frame alone sends its origin, which YouTube's player needs.
- **A refused trailer never shows YouTube's error screen.** Some trailers cannot be played in the
  viewer's country, and the import cannot know which: YouTube's oEmbed check answers the same everywhere.
  So the embed runs with `enablejsapi=1`, and Flicks listens for the player's own messages (from that
  origin and that frame only), without loading any YouTube script into the page. The frame stays hidden
  until the player reports the trailer is playing or cued. On an error (100, 101 or 150: removed, not
  embeddable, or blocked here), the card shows its poster and says the trailer can't be played here. The
  video ID is remembered in this browser, so that film shows its poster at once next time.
- **Up next.** When a film ends, the player asks for a like or pass and offers the best playable pick for
  the scene, which is not the film just watched or one already finished. It starts after a 10-second
  countdown that the viewer can cancel. With reduced motion there is no countdown, and in couch mode the
  phones decide what plays next.
- **"Pick for me"** (`POST /api/pick`) draws one of the top 12 picks, weighted 1/√rank (about 1 in 6 for
  the first, 1 in 20 for the twelfth), or anything the scene allows, uniformly. The details sheet states
  the chance, so even a random pick is explained.

## Evaluation
- Trailer coverage: 8,443 of 9,349 MovieLens films matched; **6,101 (65%) were still embeddable** when
  checked with YouTube's oEmbed endpoint (`--verify`, 13 minutes, video IDs only); 28% of the 2015 links
  are gone. The bundled catalogue: 21 of 33 films.
- A Discover page of 8 cards on 9,349 films with 40 ratings: 77 ms median with 100 titles already shown,
  96 ms with 300 (two rankings over one taste pass); 70 ms over HTTP. "Pick for me": 54 ms
  (`python -m flicks.benchmark`).

## Alternatives considered
- **Wikidata YouTube IDs** (P1651): current and public domain, but for films they are mostly full-length
  uploads (8,000 to 10,000 seconds), not trailers.
- **TMDB**: current trailers, but every user would need a personal API key, and its terms require
  attribution. The proof of concept's choice; a good optional source later.
- **Downloading trailers (yt-dlp)**: offline trailers, but against YouTube's terms, and tens of megabytes each.
- **A separate trailer app** (the proof of concept as it was): two databases and two servers to keep in
  step, and reactions that change nothing.
- **Weighting "Pick for me" by score**: gaps between scores vary so much between profiles that one
  profile's draw collapsed onto the top pick while another's was almost uniform.

## Consequences
- Discover's quality is the recommender's: it adds ordering and variety, not a new model.
- A third of 2015 trailers are gone and more will go; re-run the import with `--verify` occasionally.
- Coverage is lower than 65% in practice, by however many trailers are blocked in the viewer's country
  (the first one met in Canada was *Forrest Gump*'s). Each is found once, on the card, and then skipped.
- Turning trailers on sends YouTube the viewer's IP address and which trailers play, which is why the
  feature is off by default and asks first. Ratings and history are never sent.
