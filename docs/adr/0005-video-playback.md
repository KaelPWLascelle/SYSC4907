# 0005. Direct play over HTTP range requests; transcoding is optional

**Status:** Accepted

## Context
Playback is the proposal's primary objective. Browsers natively play MP4 (H.264/AAC) and WebM
(VP8/VP9/AV1, Opus/Vorbis); MKV and HEVC support varies by browser. Transcoding needs ffmpeg, which
is not installed everywhere and is CPU-heavy on low-end hardware.

## Decision
- A media library maps local files to catalogue titles using Jellyfin/Plex-style names
  (`Title (Year).ext`) or the content ID (`m033.webm`), scanned at startup from `--media` folders.
- The server streams files with range requests (`/media/<content id>`), only for matched titles.
- The UI marks titles as playable, plays them in a `<video>` element, saves progress, and offers
  "Continue watching". Watch progress is stored locally (migration 2).
- Couch-mode remote actions drive the real player.
- Transcoding/remuxing through ffmpeg is a later, optional capability, detected at runtime and never
  required.

## Consequences
Files the browser cannot decode show a clear "format not supported" message instead of a broken
player. Demo media should be MP4 or WebM; public-domain films (for example *A Trip to the Moon*,
*Sherlock Jr.*, *The General*) are good candidates.
