"""Runtime settings. The CLI builds one; tests build their own with temporary paths."""
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = Path(__file__).parent
DEFAULT_CATALOG = PACKAGE/'data'/'movies.json'
DEFAULT_STATIC = PACKAGE/'static'
HOME = Path.home()/'.flicks'


def default_db():
    """~/.flicks/feedback.sqlite3, or the pre-rebrand ~/.kevin file when only that exists, so ratings carry over."""
    current, legacy = Path.home()/'.flicks'/'feedback.sqlite3', Path.home()/'.kevin'/'feedback.sqlite3'
    return legacy if legacy.exists() and not current.exists() else current


@dataclass(frozen=True)
class Settings:
    db: Path
    catalog: Path = DEFAULT_CATALOG
    port: int = 8765
    static_dir: Path = DEFAULT_STATIC
    poster_dir: Path | None = None
    media_dirs: tuple[Path, ...] = ()
    tags: Path | None = None
    couch: bool = False
    couch_host: str | None = None
    couch_port: int = 8770
    # Extra browser origins allowed to call the API, e.g. the Vite dev server (`--dev`).
    extra_origins: tuple[str, ...] = field(default=())

    @property
    def origins(self):
        """Pages allowed to make requests: this server's own origin, plus any configured extras."""
        return frozenset({f'http://127.0.0.1:{self.port}', f'http://localhost:{self.port}', *self.extra_origins})
