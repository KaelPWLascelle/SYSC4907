# Catalogue

`movies.json` bundles 36 real film titles (including three short films) selected
for recognizable examples and varied genres, moods, runtimes, and intensity.
It is a small hand-curated demonstration dataset, **not MovieLens**, a representative
sample, or a source of measured audience preferences.

Titles, release years, and approximate runtimes are manually entered factual
metadata. Runtime varies by release, restoration, projection speed, and credits;
verify against the actual media file before using runtime as a playback constraint.
These entries have not received an independent catalogue audit.
Descriptions are newly written short summaries, not scraped or copied synopses.
Genres, theme tags, mood labels, and intensity values are editorial annotations
created for this project. They are subjective and are not age/content ratings.
No posters, videos, external assets, audience ratings, or third-party dataset
extracts are bundled; posters are an optional local cache (`python -m flicks.posters`).
No rights to the underlying films are conveyed.

## MovieLens

`python -m flicks.datasets.movielens` builds `~/.flicks/catalogs/movielens-small.json` from the
MovieLens "latest-small" dataset:

- **From MovieLens:** titles (with "Matrix, The" reordered), years, genres (mapped to this
  catalogue's vocabulary) and up to five of the most-applied user tags.
- **From Wikidata (CC0), matched by IMDb ID:** runtimes (the shortest plausible one when there are
  several cuts) and the English Wikipedia article.
- **From English Wikipedia (CC BY-SA 4.0):** the first sentences of each article's introduction as
  the description, with Wikidata's short description as a fallback.
- **Estimated:** moods and intensity, from genres (`flicks/datasets/genres.py`). They are a baseline,
  not editorial labels; System One tagging can replace them.

Titles without a year, genres, runtime or description are skipped, and the provenance file next to
the catalogue (`movielens-small.provenance.json`) records how many were skipped and why, along with
the dataset checksum, license and citation.

MovieLens may be used for non-commercial research. Publications must acknowledge it, and any
redistribution, including derived catalogues, must carry the same conditions. Cite: F. Maxwell Harper
and Joseph A. Konstan. 2015. The MovieLens Datasets: History and Context. *ACM Transactions on
Interactive Intelligent Systems* 5, 4: 19:1–19:19. <https://doi.org/10.1145/2827872>. Flicks does not
imply any endorsement by the University of Minnesota or GroupLens.

## Bring your own catalogue

Run `flicks --catalog path/to/catalog.json --db path/to/profile.sqlite3`.
Use a nonempty JSON array; every object must have exactly these fields:

```json
{
  "id": "stable-provider-id",
  "title": "Example title",
  "year": 2026,
  "kind": "movie",
  "minutes": 90,
  "genres": ["drama"],
  "tags": ["friendship", "travel"],
  "moods": ["reflective"],
  "intensity": 0.3,
  "description": "An original or appropriately licensed description."
}
```

IDs must be unique nonempty strings. Keep them stable and namespace them by source
when combining datasets; ratings attach to IDs. Unknown old IDs are ignored by
the ranker. Use a separate database for unrelated catalogues to avoid collisions.
Mood values: relaxing, uplifting, curious, tense, reflective. Intensity is a finite
number in [0,1]; runtime is a positive integer. Text arrays must be nonempty.
Startup validation rejects invalid catalogues. `kind` is extensible; `episode` marks
podcast episodes, which may also have a `series` (the show's name). Cross-domain
ranking (films and episodes together) has not been evaluated.

## Podcasts

`python -m flicks.datasets.podcasts` builds `~/.flicks/catalogs/podcasts.json` from
RSS feeds (nine long-form starter shows, or `--feed URL` / `--feeds FILE`). Episode
IDs are `pod` plus a hash of the feed URL and the episode's GUID, so they are stable
across imports and never collide with film IDs. Genres are the shows' Apple Podcasts
categories; moods and intensity are estimated from them (`flicks/datasets/genres.py`).
Beside the catalogue, `podcasts.episodes.json` (format `flicks-podcasts-v1`) records
each episode's show, page and audio URL, plus which feeds failed and why episodes were
skipped. Episodes belong to their publishers: they are downloaded only on request, for
personal listening, and stay out of git.

For a larger study, obtain a licensed dataset, record its version, source, license,
and checksum, and separate objective metadata from experimental annotations.
Do not treat this curated fixture as evidence of real recommendation accuracy.
