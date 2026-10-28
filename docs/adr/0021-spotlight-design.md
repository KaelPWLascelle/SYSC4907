# 0021. Spotlight: a dark room lit by the film in focus

**Status:** Accepted · replaces the Apple-style theme of the interface

## Context
The interface copied Apple's system look: the system font, black, one blue accent, pill chips, and a
blue-to-purple gradient on the logo, the chat button and the avatars. It worked, but nothing about it said
"Flicks", and reviewers described it as generic. We compared two directions as clickable prototypes
built from the real catalogue: a playful cinema letterboard, and a minimal TV-style page. The letterboard
was fun but too loud for horror, drama and documentaries; the TV page was calm but anonymous. We chose
the TV page with a few cinema details that carry information rather than decorate.

## Decision
- **No brand colour; the film lights the room.** The page is black and white. Tonight's pick stands under
  a spotlight, and the page takes its colour from that poster: `lib/tone.ts` averages the cached poster on
  a canvas (posters come from this server, so the canvas can read them), weighting saturated pixels, and
  keeps the result dark. Titles without a poster get a colour from their ID. The beam is wide for gentle
  films and tight for tense ones (`content.intensity`).
- **One warm colour, for lights that mean something.** `--bulb` marks the dot on the i in the wordmark,
  runtime as a row of bulbs against the time you said you have (ten minutes each; a series lights whole
  episodes), the score bars in "Why this pick", likes, and the Your taste charts. Like and pass differ in
  lightness as well as hue (bulb and red), so they stay apart for colour-blind viewers (ADR 0015).
- **One typeface, self-hosted.** Hanken Grotesk (SIL Open Font License) from `@fontsource-variable`, bundled
  as files. Nothing is fetched from a font CDN (ADR 0001), and fonts are never inlined as `data:` URLs,
  which the server's Content-Security-Policy blocks.
- **The stage does not move.** On wide screens the hero has a fixed height and the copy stands on its
  floor; the title is sized to its length so it never needs more than two lines. Pointing at or focusing
  a pick in the row puts it under the spotlight (like a TV remote's focus) without moving anything below.
- **A few details from the cinema, each with a job:**
  - Pressing the bulb on the i, or L, dims the house lights: everything but the spotlit poster fades, and
    the pointer carries a faint torch. Escape brings them back.
  - A film started from the beginning counts in with three frames of film leader (skipped when the viewer
    asks for less motion); nothing plays underneath.
  - Paused for five minutes, the player becomes an intermission card: what is left, when it would end if
    resumed now, and a way back in.
  - Continue watching is a row of ticket stubs, torn where you stopped.
  - The footer is the end credits, and says where your data went: nowhere.
  - Your taste adds a web: one thread per genre, with your shape drawn on it (the list below stays the way
    to read and browse the same numbers).
- **The app icon is the i:** a white stem and a warm bulb on black (`scripts/make_icons.py`).

## Consequences
- Motion stays sparing: the title's letters settle in when the pick changes, the bulbs light in order, and
  dust drifts in the beam. All of it stops under `prefers-reduced-motion`.
- Accessible names did not change, so the unit and end-to-end tests needed no rewrites; new tests cover
  the spotlight following focus, the house lights, the runtime bulbs, the leader and the intermission.
- Couch mode's host panel and the phone page take the new tokens but keep their layout; a redrawn couch
  view (seats that fill as phones join) is left for the couch dashboard work.
