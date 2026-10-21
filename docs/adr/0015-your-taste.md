# 0015. "Your taste": a view of the profile, a tunable mix, and quality beyond accuracy

**Status:** Accepted · amends [0009](0009-popularity-prior.md) (prior strength)

## Context
Explanations were per pick ("why this pick"); nothing showed what Flicks had learned about a person as a
whole, and the factor weights (taste 0.55, mood 0.20, intensity 0.15, discovery 0.10) were fixed. The
offline evaluation measured only accuracy (HR@10, NDCG@10), which rewards recommending what is popular.

## Decision
- **"Your taste" view** (`flicks/taste.py`, `GET /api/taste`, `TasteSheet.tsx`), built only from data the
  ranking uses, so it never claims something the ranking does not:
  - **Genre lean:** per genre, (likes − passes) / (likes + passes + 2), a diverging bar chart (blue toward,
    red away, neutral midpoint) with a table view, tooltips, and a link to browse each genre.
  - **Themes:** the catalogue's curated tags, weighted by rarity (IDF), likes minus 0.7 × passes; tags that
    restate a genre are left to the genre chart. Description words were tried first and rejected: Wikipedia
    introductions made the "themes" names and numbers.
  - **Films shaping your picks:** how many of the top 40 picks name each liked film as the collaborative
    reason ("fans of X also like this").
- **A tunable mix.** The factor weights are now the session's `mix`: four non-negative numbers summing to 1,
  validated like every other scene setting, so scores stay in [0, 1] and factors still add up to them. The
  view previews the new top five live (with movement markers) before the user applies it; the mix is
  remembered per profile in the browser.
- **Chart colours** come from a validated palette (CVD separation, normal-vision floor and 3:1 contrast on
  the dark surface all pass); identity is never colour alone (labels, legend, table view).
- **Quality beyond accuracy.** `python -m flicks.datasets.evaluation` now also reports, per model and
  profile size, catalogue coverage of the top 10, personalisation (1 − mean overlap between two users'
  lists), genre diversity within a list, and novelty (mean popularity percentile; 0 = most popular).
- **Prior strength 2.0 → 1.0.** See the evaluation below.

## Evaluation (test users; docs/evaluation.md)

| 3 likes | HR@10 | NDCG@10 | Coverage | Personalisation | Popularity pct. |
|---|---:|---:|---:|---:|---:|
| popularity | 0.127 ± 0.036 | 0.072 | 0.010 | 0.676 | 0.001 |
| hybrid, no prior | 0.050 ± 0.024 | 0.026 | 0.106 | 0.987 | 0.098 |
| hybrid + prior 2.0 (NDCG-best) | 0.136 ± 0.037 | 0.078 | 0.020 | 0.878 | 0.003 |
| **hybrid + prior 1.0 (shipped)** | **0.108 ± 0.034** | **0.061** | **0.038** | **0.942** | **0.009** |

| 10 likes | HR@10 | NDCG@10 | Coverage | Personalisation | Popularity pct. |
|---|---:|---:|---:|---:|---:|
| popularity | 0.127 ± 0.036 | 0.072 | 0.010 | 0.676 | 0.001 |
| hybrid + prior 2.0 | 0.133 ± 0.037 | 0.082 | 0.041 | 0.939 | 0.013 |
| **hybrid + prior 1.0 (shipped)** | **0.121 ± 0.035** | **0.069** | **0.053** | **0.953** | **0.023** |

With full histories the two strengths are within 0.003 HR of each other.

**Reading.** The NDCG-best prior makes a new user's top 10 almost the same short list of blockbusters for
everyone: 2% of the catalogue across all test users, from the most popular 0.3%. That wins hit rate partly
because held-out liked films skew popular. On development users, 1.0 had the same hit rate as 2.0 with 3 and
10 likes; on test users it is lower (0.108 against 0.136 with 3 likes, inside each other's 95% intervals)
while nearly doubling coverage and raising personalisation from 0.88 to 0.94. Flicks ships 1.0 because a
personal recommender that shows everyone the same films fails its purpose; this is a product judgment, and
2.0 is one constant away (`PopularityPrior.STRENGTH`). A user study (docs/evaluation.md) should settle it.

## Consequences
- Every new chart in the view must come from data the ranking uses and offer a non-colour reading.
- Any change to the ranking should be evaluated on both accuracy and the beyond-accuracy columns.
