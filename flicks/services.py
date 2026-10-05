"""Builds the application's long-lived objects from Settings, so the HTTP layer only wires requests to them."""
from dataclasses import dataclass

from .api.guest import CouchManager
from .collaborative import HybridTaste, ItemNeighbours
from .commands import CommandInterpreter
from .core import Recommender, TfidfTaste, load_catalog
from .db import Database
from .intent import SystemOneInterpreter
from .media import MediaLibrary
from .podcasts import PodcastIndex, PodcastLibrary, episodes_path
from .posters import PosterLibrary
from .repositories import RatingsRepository, WatchHistoryRepository
from .search import TitleIndex
from .tagging import TaggedDecision, load_tags
from .voice import LocalWhisper


@dataclass
class Services:
    catalog: list
    ids: frozenset
    titles: TitleIndex
    recommender: Recommender
    ratings: RatingsRepository
    history: WatchHistoryRepository
    interpreter: object       # CommandInterpreter or SystemOneInterpreter
    speech: object            # LocalWhisper or a test double with status() and transcribe()
    posters: PosterLibrary | None
    media: MediaLibrary
    podcasts: PodcastLibrary | None
    couch: CouchManager | None
    tagged: bool
    collaborative: bool


def build_services(settings, *, speech=None, system_one=None):
    """system_one: a DecisionClient whose backend must be local (SystemOneInterpreter enforces it)."""
    catalog = load_catalog(settings.catalog)
    podcasts = None
    if settings.podcasts:
        episodes = load_catalog(settings.podcasts)
        clashes = {item.id for item in catalog} & {item.id for item in episodes}
        if clashes:
            raise ValueError(f'The podcast catalogue reuses catalogue IDs, e.g. {min(clashes)}')
        catalog = catalog + episodes
        index = PodcastIndex.load(episodes_path(settings.podcasts), {item.id for item in episodes})
        podcasts = PodcastLibrary(index, settings.podcast_downloads)
    ids = frozenset(item.id for item in catalog)
    decision = TaggedDecision(load_tags(settings.tags, catalog)) if settings.tags else None
    taste = TfidfTaste(catalog)
    if settings.neighbours:
        neighbours = ItemNeighbours.load(settings.neighbours, ids)
        taste = HybridTaste(taste, neighbours, {item.id: item.title for item in catalog})
    database = Database(settings.db)
    posters = PosterLibrary(settings.poster_dir, ids) if settings.poster_dir else None
    couch = CouchManager(settings.couch_host, settings.couch_port, posters=posters,
                         static_dir=settings.static_dir) if settings.couch else None
    return Services(
        catalog=catalog, ids=ids, titles=TitleIndex(catalog),
        recommender=Recommender(catalog, taste=taste, decision=decision),
        ratings=RatingsRepository(database),
        history=WatchHistoryRepository(database),
        interpreter=SystemOneInterpreter(catalog, system_one) if system_one else CommandInterpreter(catalog),
        speech=speech if speech is not None else LocalWhisper(),
        posters=posters,
        media=MediaLibrary(settings.media_dirs, catalog),
        podcasts=podcasts,
        couch=couch,
        tagged=decision is not None,
        collaborative=isinstance(taste, HybridTaste),
    )
