# 0009. New users start from a popularity prior that gives way as they rate

**Status:** Accepted

## Context
A new user has no ratings, so the content and collaborative models (ADR 0008) know nothing about
them, and their first screen is ranked by scene alone. On held-out MovieLens ratings, plain
popularity found a user's liked film more than twice as often as the hybrid for users with 3 likes
(HR@10 0.127 against 0.050). The first screen is where an app makes its impression, and it was
the weakest one.

## Decision
- **The neighbour file also records popularity:** how many MovieLens raters liked each film
  (rating ≥ 4). Like the neighbours, it is a public aggregate computed at build time, so nothing
  about the user leaves the device (ADR 0001). Files without it still load, and simply have no prior.
- **Taste starts from popularity and gives way to the user** (`PopularityPrior` in
  `flicks/collaborative.py`): `taste = w·popularity + (1 − w)·hybrid taste`, with
  `w = 2 / (2 + number of likes and passes)` and popularity log-scaled to [0, 1]. With no ratings the
  picks are widely liked films that fit the scene; after 2 ratings the prior has half the weight;
  after 18, a tenth.
- **The strength (2) is chosen by evaluation** on development users, for the best mean NDCG@10 over
  3 likes, 10 likes and full histories, on top of the tuned blend (docs/evaluation.md).
- **Explanations stay honest.** A pick is marked `popular` only when the prior supplied at least
  half of its taste score; only then does the interface call it a "Crowd favourite".

## Alternatives considered
- **Popularity as a fixed decision factor:** it would never fade, so established users would keep
  getting the same popular films.
- **An onboarding questionnaire** (pick genres or rate a few films before the first screen): useful
  later, but it delays the first screen and still needs a sensible default ranking.
- **Showing popularity only when there are no ratings:** a cliff, where the first like suddenly
  replaces the whole list with a model that knows one film.

## Consequences
- **New users get much better first picks:** HR@10 0.136 with 3 likes (0.050 without the prior), and
  0.133 with 10 likes (0.102), matching or edging past plain popularity while staying personal.
- **A pull toward the popular.** Early picks favour well-known films, which suits a first screen
  but narrows discovery; the session's novelty setting still works against it. Part of the
  offline gain reflects that held-out liked films skew popular, so the user study (docs/evaluation.md)
  should check that people actually prefer these picks.
- **With long histories the prior barely matters,** and plain popularity is still slightly ahead
  there (0.127 against 0.108, within the margin of error).
