# Demo catalogue v1

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
created for this prototype. They are subjective and are not age/content ratings.
No posters, videos, external assets, audience ratings, or third-party dataset
extracts are bundled. No rights to the underlying films are conveyed.

## Bring your own catalogue

Run `python3 -m kevin --catalog path/to/catalog.json --db path/to/profile.sqlite3`.
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
Startup validation rejects invalid catalogues. `kind` is extensible (episode,
podcast, lecture, etc.), though cross-domain ranking has not been evaluated.

For a larger study, obtain a licensed dataset, record its version, source, license,
and checksum, and separate objective metadata from experimental annotations.
Do not treat this curated fixture as evidence of real recommendation accuracy.
