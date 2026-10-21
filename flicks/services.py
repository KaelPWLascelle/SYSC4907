"""Builds the application's long-lived objects from Settings, so the HTTP layer only wires requests to them."""
from dataclasses import dataclass
from pathlib import Path

from .api.guest import CouchManager
from .archive import ArchiveIndex
from .assistant.agent import AgentInterpreter
from .assistant.ask_student import Student, StudentInterpreter
from .assistant.commands import CommandInterpreter
from .assistant.intent import SystemOneInterpreter
from .assistant.llm import Chat, LocalChat
from .assistant.narrator import Narrator
from .assistant.voice import LocalWhisper
from .collaborative import HybridTaste, ItemNeighbours, PopularityPrior
from .core import Recommender, TfidfTaste, load_catalog
from .db import Database
from .discover import Discover
from .media import MediaLibrary
from .podcasts import PodcastIndex, PodcastLibrary, episodes_path
from .posters import PosterLibrary
from .profiles import ProfileSessions
from .relay import Streams
from .repositories import ProfileRepository, RatingsRepository, WatchHistoryRepository
from .search import TitleIndex
from .tagging import TaggedDecision, load_tags
from .taste import TasteSummary
from .trailers import TrailerIndex


@dataclass
class Services:
    catalog: list
    ids: frozenset
    titles: TitleIndex
    similar: object             # the taste model behind "more like X" (no popularity prior)
    taste: TasteSummary         # "Your taste": genres, themes and influences from the ratings
    discover: Discover          # the Discover feed and "Pick for me"
    recommender: Recommender
    profiles: ProfileRepository
    sessions: ProfileSessions   # who is signed in to which profile (in memory)
    ratings: RatingsRepository          # profile 1's; routes use the request's profile (api/deps.viewer)
    history: WatchHistoryRepository
    interpreter: object       # rules (or rules + System One), wrapped by the Ask student and optionally the LLM agent
    speech: object            # LocalWhisper or a test double with status() and transcribe()
    posters: PosterLibrary | None
    media: MediaLibrary
    podcasts: PodcastLibrary | None
    streams: Streams            # titles that play from elsewhere through the relay (episodes, Archive films)
    couch: CouchManager | None
    tagged: bool
    collaborative: bool
    popularity_prior: bool
    chat: Chat | None = None            # the optional local language model (llm.LocalChat)
    narrator: Narrator | None = None

    def llm_status(self):
        if self.chat is None:
            return {'available': False, 'name': None, 'message': 'No local language model is configured'}
        status = getattr(self.chat, 'status', None)
        return status() if status else {'available': True, 'name': self.chat.name, 'message': 'Ready'}


def build_services(settings, *, speech=None, system_one=None, chat=None):
    """system_one: a DecisionClient whose backend must be local (SystemOneInterpreter enforces it).
    chat: a language model client (llm.Chat); by default one is made from settings.llm_url, which must be local.
    """
    catalog = load_catalog(settings.catalog)
    films = {item.id for item in catalog}
    podcasts = None
    if settings.podcasts:
        episodes = load_catalog(settings.podcasts)
        clashes = films & {item.id for item in episodes}
        if clashes:
            raise ValueError(f'The podcast catalogue reuses catalogue IDs, e.g. {min(clashes)}')
        catalog = catalog + episodes
        index = PodcastIndex.load(episodes_path(settings.podcasts), {item.id for item in episodes})
        podcasts = PodcastLibrary(index, settings.podcast_downloads)
    ids = frozenset(item.id for item in catalog)
    remotes = podcasts.index.remotes() if podcasts else {}
    if settings.archive:
        remotes |= ArchiveIndex.load(settings.archive, films).remotes()
    decision = TaggedDecision(load_tags(settings.tags, catalog)) if settings.tags else None
    taste = similar = TfidfTaste(catalog)
    collaborative = prior = False
    likes = {}
    if settings.neighbours:
        neighbours = ItemNeighbours.load(settings.neighbours, ids)
        taste = HybridTaste(taste, neighbours, {item.id: item.title for item in catalog})
        collaborative = True
        likes = neighbours.popularity
        if neighbours.popularity:
            # The ratings describe the film catalogue only; podcast episodes keep their own taste.
            similar = taste  # "more like X" should be about X, not about what is popular
            taste = PopularityPrior(taste, neighbours.popularity, covered=films)
            prior = True
    titles = TitleIndex(catalog, likes)
    media = MediaLibrary(settings.media_dirs, catalog)
    streams = Streams(remotes)

    def playable(content_id):
        return content_id in media.files or content_id in streams.remotes or bool(podcasts and podcasts.file(content_id))

    database = Database(settings.db)
    posters = PosterLibrary(settings.poster_dir, ids) if settings.poster_dir else None
    couch = CouchManager(settings.couch_host, settings.couch_port, posters=posters,
                         static_dir=settings.static_dir) if settings.couch else None
    interpreter = (SystemOneInterpreter(catalog, system_one, titles=titles, playable=playable) if system_one
                   else CommandInterpreter(catalog, titles, playable))
    if settings.ask_student and Path(settings.ask_student).is_file():
        # The distilled Ask student (docs/adr/0014-ask-student.md): tiny, in-process, on by default.
        interpreter = StudentInterpreter(interpreter, Student.load(settings.ask_student), catalog, titles, playable)
    if chat is None and settings.llm_url:
        chat = LocalChat(settings.llm_url, settings.llm_model)
    if chat is not None:
        interpreter = AgentInterpreter(interpreter, chat, catalog, titles, playable)
    recommender = Recommender(catalog, taste=taste, decision=decision, playable=playable)
    trailers = TrailerIndex.load(settings.trailers, films) if settings.trailers else TrailerIndex()

    def media_kind(content_id):
        return 'file' if content_id in media.files else 'stream' if content_id in streams.remotes else None

    return Services(
        catalog=catalog, ids=ids, titles=titles, similar=similar,
        recommender=recommender,
        taste=TasteSummary(catalog, recommender),
        discover=Discover(recommender, media_kind, trailers),
        profiles=ProfileRepository(database),
        sessions=ProfileSessions(),
        ratings=RatingsRepository(database),
        history=WatchHistoryRepository(database),
        interpreter=interpreter,
        speech=speech if speech is not None else LocalWhisper(),
        posters=posters,
        media=media,
        podcasts=podcasts,
        streams=streams,
        couch=couch,
        tagged=decision is not None,
        collaborative=collaborative,
        popularity_prior=prior,
        chat=chat,
        narrator=Narrator(chat, catalog) if chat is not None else None,
    )
