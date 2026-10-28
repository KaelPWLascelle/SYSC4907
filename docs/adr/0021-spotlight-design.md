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
  - Your taste adds a web: one thread per genre, with your shape drawn on it and the films you rated
    hanging in it (`/api/taste` now returns them, with their genres). Choosing a thread explains it in a
    sentence, shows its films and offers to browse it. The list below stays the way to read and browse the
    same numbers. "Films shaping your picks" is a row of bulbs, one per pick.
  - Couch mode is drawn as the room: the code to scan, the shortlist on screen, and a sofa that fills as
    phones join, with a bulb over each seat that lights when that guest has voted on everything. At the
    reveal each title's votes show as bulbs, the others step back, and the spotlight finds the group's pick.
  - The room follows the clock: a little warmer in the evening, cooler and lower from 10 pm, when Tonight
    offers picks that end in 90 minutes. `?hour=23` previews it.
  - Posters in a row tilt toward the pointer and catch the light where it points.
- **"Your usual night", drawn rather than chosen.** On Your taste, a shape you drag across for how tense
  and up or down for how long: round and soft for a gentle night, a star with sharper points for a tense
  one, bigger for a longer one. Saved per profile in this browser (like the mix), it sets the intensity and
  length a visit starts from and the scene Reset returns to; Tonight can still ask for something else.
- **The app icon is the i:** a white stem and a warm bulb on black (`scripts/make_icons.py`).

## Consequences
- Motion stays sparing: the title's letters settle in when the pick changes, the bulbs light in order, and
  dust drifts in the beam. All of it stops under `prefers-reduced-motion`.
- Accessible names did not change, so the unit and end-to-end tests needed no rewrites; new tests cover
  the spotlight following focus, the house lights, the runtime bulbs, the leader and the intermission.
- The couch room shows votes per title, not per person: the server reports each guest's progress and each
  title's totals, never who voted for what, and the view keeps it that way. The phone page takes the new
  tokens but keeps its layout.
