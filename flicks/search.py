"""Lookup and search over the loaded catalogue, in memory (docs/adr/0007-catalogue-artifact.md)."""
from .media import normalize


class TitleIndex:
    """Titles by ID, the genre vocabulary, and accent-insensitive search in catalogue order."""

    def __init__(self, catalog):
        self.items = list(catalog)
        self.by_id = {item.id: item for item in self.items}
        self.genres = sorted({genre for item in self.items for genre in item.genres})
        self._text = [normalize(' '.join([item.title, str(item.year), *item.genres, *item.tags])) for item in self.items]

    def __len__(self):
        return len(self.items)

    def search(self, query='', keep=None, offset=0, limit=48):
        """(page of titles, total matches). Every query word must appear; `keep(item)` filters further."""
        words = normalize(query).split()
        matches = [item for item, text in zip(self.items, self._text, strict=True)
                   if all(word in text for word in words) and (keep is None or keep(item))]
        return matches[offset:offset + limit], len(matches)
