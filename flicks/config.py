"""Runtime settings. The CLI builds one; tests build their own with temporary paths."""
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = Path(__file__).parent
DEFAULT_CATALOG = PACKAGE/'data'/'movies.json'
DEFAULT_STATIC = PACKAGE/'static'
# Per-user data lives here: ratings and watch history, and the poster cache.
HOME = Path.home()/'.flicks'
DEFAULT_DB = HOME/'feedback.sqlite3'
DEFAULT_POSTERS = HOME/'posters'
DEFAULT_SERIES = HOME/'catalogs'/'series.json'
DEFAULT_MOVIELENS = HOME/'catalogs'/'movielens-small.json'  # written by `flicks setup` (flicks.datasets.movielens)
# The small language model `flicks setup --model` downloads; used automatically when present (flicks/setup.py).
# Granite 4.0 1B since the November 2026 benchmark (docs/llm-benchmark.md).
DEFAULT_MODEL = HOME/'models'/'granite-4.0-1b-Q4_K_M.gguf'
# Defaults an earlier `flicks setup --model` downloaded, still used until the new one is installed.
EARLIER_MODELS = (HOME/'models'/'Qwen3.5-2B-Q4_K_M.gguf',)


def installed_model():
    """The model file `flicks setup --model` installed: the current default, else an earlier one, else None."""
    return next((path for path in (DEFAULT_MODEL, *EARLIER_MODELS) if path.is_file()), None)


def default_films():
    """The film catalogue to use when none is named: the imported MovieLens one, or the bundled demo."""
    return DEFAULT_MOVIELENS if DEFAULT_MOVIELENS.is_file() else DEFAULT_CATALOG


@dataclass(frozen=True)
class Settings:
    db: Path
    catalog: Path = DEFAULT_CATALOG
    port: int = 8765
    static_dir: Path = DEFAULT_STATIC
    poster_dir: Path | None = None
    media_dirs: tuple[Path, ...] = ()
    tags: Path | None = None
    # Item-to-item neighbours for collaborative filtering (flicks.datasets.neighbours); None: content only.
    neighbours: Path | None = None
    # TV series shown beside the films (flicks.datasets.tvmaze); None: films only.
    series: Path | None = None
    # Public-domain films to stream from the Internet Archive (flicks.datasets.archive); None: none.
    archive: Path | None = None
    # Trailer video IDs for the Discover feed (flicks.datasets.trailers); None: previews and posters only.
    trailers: Path | None = None
    # Couch mode is offered in the interface; nothing listens on the network until a session starts.
    couch: bool = True
    couch_host: str | None = None
    couch_port: int = 8770
    # The distilled Ask student's weights (flicks.datasets.ask); None turns it off.
    ask_student: Path | None = PACKAGE/'data'/'ask_student.json'
    # A language model on this machine (OpenAI-compatible, e.g. Ollama) for the Ask agent and narrated
    # explanations; None: Flicks works without one (docs/adr/0013-local-llm.md).
    llm_url: str | None = None
    llm_model: str = 'qwen3.5:2b'
    # A GGUF model run inside the Flicks process (llama.cpp, the `llm` extra) instead of a model server:
    # questions about a title, narrated explanations and the Ask agent (docs/adr/0019-title-chat.md).
    llm_file: Path | None = None
    llm_gpu: bool = True        # False: CPU only, as on a laptop without a usable GPU
    # Extra browser origins allowed to call the API, e.g. the Vite dev server (`--dev`).
    extra_origins: tuple[str, ...] = field(default=())

    @property
    def origins(self):
        """Pages allowed to make requests: this server's own origin, plus any configured extras."""
        return frozenset({f'http://127.0.0.1:{self.port}', f'http://localhost:{self.port}', *self.extra_origins})
