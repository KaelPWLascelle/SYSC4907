# 0008. Item-to-item collaborative filtering, precomputed from public ratings

**Status:** Accepted

## Context
The proposal promises collaborative filtering, and the content model alone recommends by shared
words (liking *Star Wars* suggested *Spaceballs* and *Space Buddies*). Collaborative filtering
normally needs many users' behaviour, which conflicts with keeping each user's data on their device
(ADR 0001).

## Decision
- **Similarities come from a public dataset, never from users.** At build time
  (`flicks/datasets/neighbours.py`, NumPy), adjusted cosine similarity between films is computed
  from MovieLens ratings: deviations from each rater's mean, over the users who rated both, shrunk
  toward zero by `n / (n + 10)` when few did. Each film keeps its 30 most similar films. The app
  ships no ratings; it reads the precomputed neighbour file.
- **At runtime the user's own likes are looked up against those neighbours, on the device**
  (`flicks/collaborative.py`): prediction = Σ similarity·rating / Σ similarity over the rated films
  that point to a title.
- **A hybrid, not a replacement.** Each title's taste moves from its content score toward its
  collaborative prediction by `support / (support + 2)`, where support is how much collaborative
  evidence it has. Titles with no evidence keep their content score, which covers the third of the
  catalogue too rarely rated to have neighbours.
- **Explanations name the liked films** that contributed ("Fans of *The Empire Strikes Back* also
  like this").
- **The blend strength (2) is chosen by evaluation**, on development users, for the best mean NDCG@10
  over new users (3 and 10 likes) and full histories (docs/evaluation.md).

## Alternatives considered
- **Matrix factorization (ALS, SVD):** often more accurate, but opaque to explain, needs per-user
  fitting or fold-in at runtime, and adds a numerical dependency to the app.
- **User-to-user neighbours:** would compare the user with MovieLens users at runtime, shipping their
  rating histories with the app.
- **Popularity as the recommender:** a strong baseline (see evaluation), but everyone gets the same
  list, which is not personal recommendation.

## Consequences
- **Build step:** NumPy is a build-time extra (`[datasets]`), not a runtime dependency.
- **Coverage:** neighbours exist only for films in the ratings dataset (6,175 of 9,349 titles).
- **Not yet better than popularity.** On held-out MovieLens ratings, plain popularity still
  matches or beats the hybrid, especially for new users. A popularity prior for users with few
  ratings is the natural next step.
