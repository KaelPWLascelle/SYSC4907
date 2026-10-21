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
Startup validation rejects invalid catalogues. `kind` is free text (`movie`, `short`…),
except `series`, which marks a TV series and requires a `series` object:

```json
"series": {"seasons": 5, "episodes": 62, "ended": 2013, "network": "AMC",
           "page": "https://www.tvmaze.com/shows/169/breaking-bad", "votes": 2300000}
```

`ended` is the year it last aired, or `null` while it runs; `network` may be `null`; `page`
must be an https address; `votes` is a public popularity count (IMDb votes). A series'
`minutes` is one episode's typical length. Ranking films and series together has not been
evaluated.

## TV series

`python -m flicks.datasets.tvmaze` builds `~/.flicks/catalogs/series.json`, which Flicks loads
beside any film catalogue (`--series FILE`, or `--no-series`):

- **From TVmaze (CC BY-SA 4.0), through its free API:** names, premiere and end years, typical
  episode length, network, aired seasons and their episode counts, genres (mapped to this
  catalogue's vocabulary; the rest become tags), the summary's first sentences as the
  description, and the show's page, which the details sheet links to as credit.
- **From IMDb's non-commercial dataset (`title.ratings`), matched by the IMDb ID TVmaze records:**
  vote counts. They choose the 1,000 most-voted series (at least 5,000 votes) and feed the
  popularity prior, scaled separately from films' MovieLens likes. Personal and non-commercial use only.
- **Estimated:** moods and intensity, from genres (`flicks/datasets/genres.py`).

Only scripted, animated and documentary shows are kept; talk, reality, game and news shows are
not. IDs are `tv` plus the TVmaze ID, stable across imports and never shared with films. Beside the
catalogue, `series.artwork.json` (format `flicks-artwork-v1`) lists each cover for
`python -m flicks.posters` (a 210 px `image` and, as `full`, the original, which the poster fetch
shrinks to 330 px when Pillow is installed), and `series.provenance.json` records the sources, licences, and how
many shows were skipped and why. Requests are cached under `~/.flicks/datasets/tvmaze`.

## Internet Archive

`python -m flicks.datasets.archive` writes `<catalogue>.archive.json` (format
`flicks-archive-v1`) beside an imported catalogue: for each film with a public-domain
copy on the Internet Archive, the item, the MP4 file, its URL and page, and the basis
for using it (`age`: released at least 96 years ago; `listed`: in Wikipedia's list of
US public-domain films, whose revision is recorded under `rights`). Uploaders' licence
labels are ignored. Items are matched by normalized title and year (within one year);
colourised versions, trailers, clips and dubs are skipped; the file must be a
browser-playable MP4 at least 60% of the catalogue runtime. Nothing is downloaded:
films stream from the Archive when played.

For a larger study, obtain a licensed dataset, record its version, source, license,
and checksum, and separate objective metadata from experimental annotations.
Do not treat this curated fixture as evidence of real recommendation accuracy.
