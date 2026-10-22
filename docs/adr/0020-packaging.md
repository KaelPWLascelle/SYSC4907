# 0020. Install with pipx, download with `flicks setup`, release a wheel with the interface built in

**Status:** Accepted · amends [0002](0002-fastapi-backend.md) (NumPy becomes a runtime dependency) and [0004](0004-react-vite-frontend.md)

## Context
Getting Flicks running took a clone, a virtualenv, Node to build the interface, and six import
commands with long flags (`flicks --catalog ~/.flicks/catalogs/movielens-small.json`). A teammate who
skipped the imports saw 36 title cards and no posters. The interface is build output and not committed,
so `pip install git+https://…` gave a server with no page. Collaborative filtering needed an extra
(`datasets`) that nobody knew to install, and the language model needed a runtime, a 1 GB file and a flag.

## Decision
- **Users install a wheel from GitHub Releases with pipx.** `.github/workflows/release.yml` runs on a
  `v*` tag: it builds the interface, builds the wheel and source distribution, checks that the tag
  matches the version, that the wheel carries `flicks/static/index.html` and that it installs and runs,
  then attaches both files to the release. pipx gives Flicks its own environment and puts `flicks` on
  the PATH on macOS, Windows and Linux. Nobody needs Node or a clone; developers still build from source.
- **One command downloads everything:** `flicks setup` runs the existing imports in order (MovieLens with
  Wikidata and Wikipedia details and collaborative filtering, Internet Archive streams, trailer IDs, TVmaze
  series, posters), reports each step, keeps going when one fails, and ends with what is installed.
  The imports cache their downloads, so setup can be stopped and run again. `--no-series` skips the slow
  step, `--only` runs one, `--check` only reports, and `--model` adds the language model.
- **Flicks finds what setup installed.** With no `--catalog`, it uses the imported MovieLens catalogue when
  present and says how to get it when not; the streams, trailers, neighbours and series beside it were
  already found automatically. The model setup downloaded is loaded when llama-cpp-python is installed
  (`--no-llm` turns it off). The trailer import now also defaults to the imported catalogue, as its
  documentation said; it used to default to the 36-film demo.
- **The model download is pinned and checked.** `flicks setup --model` fetches Qwen2.5 1.5B Instruct
  (Q4_K_M, Apache 2.0) from one Hugging Face revision, resumes an interrupted download, and keeps the file
  only if its SHA-256 matches, so the file that runs is the one the team evaluated (ADR 0019). The runtime
  stays an extra (`pipx inject flicks llama-cpp-python`): it compiles llama.cpp on some machines and most
  users never need it.
- **NumPy becomes a dependency** (amends ADR 0002's "two runtime dependencies"). `flicks setup` needs it to
  precompute collaborative filtering; without it, recommendations silently lose their best signal. The
  running app still never imports it. Pillow stays optional (it only shrinks series covers).
- **Small comforts:** `flicks` opens the browser once the server is ready (`--no-browser` to skip), and a
  port already in use is reported in one line instead of a traceback.

## Consequences
- The README's install is three commands: `pipx install <wheel URL>`, `flicks setup`, `flicks`.
- A release is a version bump in `pyproject.toml` and a matching tag; CI refuses a mismatch.
- The install grows by NumPy (about 15 MB); the wheel itself is under 1 MB.
- The model and posters are still downloaded on each user's computer and never redistributed, as the
  data licences require (MovieLens and IMDb non-commercial, TVmaze CC BY-SA, posters copyrighted).
