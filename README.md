# Flicks

[![CI](https://github.com/KaelPWLascelle/SYSC4907/actions/workflows/flicks.yml/badge.svg)](https://github.com/KaelPWLascelle/SYSC4907/actions/workflows/flicks.yml)

**A streaming app whose recommendations never leave your device.** Flicks learns your taste from the
films you like and pass on, reads the evening you describe (mood, time, intensity), and explains
every pick. It plays your own video files, remembers where you stopped, and lets everyone on the
couch vote from their phones. No online accounts, no cloud, no tracking.

Flicks is a SYSC 4907 capstone project at Carleton University, supervised by Dr. Huang
([project proposal](docs/proposal.md)).

## Install

You need **Python 3.10 or newer** and **pipx**, which installs Python apps in their own environment.

| | Install pipx |
|---|---|
| macOS | `brew install pipx` then `pipx ensurepath` |
| Windows | `py -m pip install --user pipx` then `py -m pipx ensurepath` |
| Linux | `sudo apt install pipx` (or your distribution's package) then `pipx ensurepath` |

Open a new terminal after `ensurepath`, then:

```sh
pipx install https://github.com/KaelPWLascelle/SYSC4907/releases/download/v0.5.0/flicks-0.5.0-py3-none-any.whl
flicks setup
flicks
```

1. **`pipx install`** installs Flicks, with its interface already built (no Node, no clone). Newer versions
   are on the [releases page](https://github.com/KaelPWLascelle/SYSC4907/releases).
2. **`flicks setup`** downloads the catalogues once: about 9,000 films from MovieLens with descriptions
   from Wikipedia, public-domain films to stream, trailers for Discover, about 1,000 TV series, and
   posters. The first run takes around 40 minutes, most of it the TV series (`flicks setup --no-series`
   skips them). It is safe to stop and run again, and it only downloads public data. `flicks setup --check`
   shows what is installed.
3. **`flicks`** starts the app and opens <http://127.0.0.1:8765> in your browser. Press Ctrl+C to stop it.

Without `flicks setup`, Flicks still runs, with a 36-film demo catalogue.

Your ratings, watch history and profiles stay in `~/.flicks/` (`%USERPROFILE%\.flicks` on Windows), and
survive updates. To update, run the `pipx install` line again with the new version and `--force`. To
remove Flicks, run `pipx uninstall flicks`, and delete `~/.flicks` if you also want your data gone.

### Optional: the chats' language model

The corner chat works without it. With it, a small language model inside Flicks (Qwen3.5 2B, about
1.4 GB) answers questions about any title and words the corner chat's replies:

```sh
flicks setup --model
pipx inject flicks llama-cpp-python
```

The first command downloads the model and checks its fingerprint. The second installs the runtime. On
some computers it compiles llama.cpp, which takes a few minutes and needs a C compiler: Xcode Command
Line Tools on macOS, or Visual Studio Build Tools on Windows. Flicks then loads the model automatically
(`flicks --no-llm` to turn it off). Answers take one to four seconds and can be wrong. If you
downloaded the earlier model (Qwen2.5 1.5B), run `flicks setup --model` again; the old file in
`~/.flicks/models` can then be deleted. See
[ADR 0019](docs/adr/0019-title-chat.md).

## Features

- **Personal recommendations, computed locally.** Your ratings, what the titles are about, and what
  people with similar taste enjoyed (learned in advance from public MovieLens ratings, never from other
  users), reranked for tonight. Every score is broken down into its parts.
- **Films and TV series** in one ranking. Ask for a film, a series or either; a series' time is one episode.
- **Search in everyday words.** "funny films from the 90s", "tom hanks" or "war films before 1960".
- **Ask Flicks.** Type or say "something relaxing under 90 minutes, no horror" and preview the change
  before it applies. A tiny model trained for Flicks (under 2 MB, no GPU) reads "long week, I want to
  switch off, nothing scary" into the evening's settings.
- **The corner chat.** The round button in the bottom corner asks what you're in the mood for and how much
  time you have, then offers three picks you can open, swap for others, or make the scene on Home.
- **Ask about a title.** With the optional model, ask any title "Who's in it?", "Is it scary?" or "Why this pick?".
- **Play your own files and public-domain films.** MP4 and WebM stream with seeking, and progress is
  saved. About 60 films that are public domain in the US stream from the Internet Archive.
- **Discover.** A full-screen feed, one title at a time: like or pass and the next ones change. Trailers
  from YouTube play only if you allow them.
- **Up next and "Pick for me".** Rate a film in one tap when it ends and the next pick starts. Can't
  decide? "Pick for me" draws one of your top picks and tells you the odds.
- **See and tune your taste.** Charts of the genres and themes behind your picks, and sliders for how
  much ratings, mood, intensity and discovery count.
- **Profiles on this device.** Each person's ratings and history stay apart, with an optional PIN, and a
  profile can be exported as a file.
- **Couch mode.** Phones on your Wi-Fi scan a QR code, vote with hidden ballots, and act as a remote.

## Using Flicks

### Play your films

```sh
flicks --media ~/Movies --media /Volumes/Films
```

Name files the way Jellyfin and Plex do, `A Trip to the Moon (1902).mp4` (optionally inside a folder of
the same name). MP4 (H.264/AAC) and WebM play in every browser; MKV and MOV may not, and Flicks says so
instead of failing silently.

### What `flicks setup` downloads

| Step | What you get | Source and terms |
|---|---|---|
| `films` | About 9,300 films with runtimes and descriptions, plus collaborative filtering ("fans of *Arrival* also like this") | [MovieLens](https://grouplens.org/datasets/movielens/) (non-commercial research use; cite Harper & Konstan, 2015), Wikidata (CC0), Wikipedia (CC BY-SA) |
| `streams` | A **Play** button for about 60 films that are public domain in the US | Internet Archive; see [ADR 0011](docs/adr/0011-streaming.md) |
| `trailers` | Trailer IDs for Discover; videos are never downloaded | MovieLens YouTube Trailers dataset; see [ADR 0016](docs/adr/0016-discover.md) |
| `series` | The 1,000 most-voted TV series | TVmaze (CC BY-SA) and IMDb vote counts (non-commercial); see [ADR 0018](docs/adr/0018-tv-series.md) |
| `posters` | Posters for the 3,000 most popular films and every series | Wikipedia and TVmaze; copyrighted, so they stay on your computer |
| `model` (opt-in) | The chats' language model | Qwen3.5 2B (Apache 2.0) |

Only public identifiers (titles, years, IMDb IDs) are sent while importing, and nothing is sent while you
use the app, except when you play a public-domain film or turn on trailers. `flicks setup --only posters`
runs one step. Each step is also a command of its own (for example `python -m flicks.datasets.tvmaze
--limit 300`); see [the catalogue guide](flicks/data/README.md) to bring your own catalogue.

### Ask Flicks

Press <kbd>/</kbd> and type a request, or record one if [voice](docs/voice.md) is set up:

- **Search:** "funny films from the 90s", "keaton", "war films before 1960".
- **Play a title:** "play The General".
- **Find similar titles:** "more like Alien".
- **Change the scene or rate:** "relaxing, under 90 minutes, no horror", "I hate musicals", "Like Arrival".

Searches and plays happen at once. Ratings and scene changes are shown first and change nothing until you
press Apply. Requests go to the cheapest reader that understands them: exact rules first, then the Ask
student, a classifier distilled for Flicks that answers in under a millisecond ([ADR 0014](docs/adr/0014-ask-student.md)).

### Profiles

Open the profile button (top right) to switch profiles, add one, set a PIN, or export, import, clear or
delete your data. A PIN keeps others in the household out of your profile; it does not encrypt the
database ([ADR 0012](docs/adr/0012-local-profiles.md)).

### Couch mode

Open **Couch** in the top bar and press **Start a couch session**. Nothing listens on your network until
you do. Phones on the same Wi-Fi scan the QR code, vote on a shortlist built from your scene, and the group
pick appears on the TV. Guests reach a separate server that cannot see your ratings or history, and their
names and votes are forgotten when the session ends. See [how couch mode works](docs/couch.md).

### Command-line options

`flicks --help` lists them all. The ones you are most likely to use:

| Option | Default | Purpose |
|---|---|---|
| `--media DIR` | none | Folder of video files to play; repeat for more folders |
| `--port N` | `8765` | Local port for the app |
| `--db FILE` | `~/.flicks/feedback.sqlite3` | Profiles, ratings and watch history |
| `--no-browser` | opens it | Don't open the browser on start |
| `--no-series` | series on when installed | Films only |
| `--no-couch` | couch on | Hide couch mode |
| `--no-llm` | model on when installed | Don't load the language model |
| `--llm-cpu` | GPU when available | Run the language model on the CPU only |
| `--catalog FILE` | the imported films, else the demo | Your own catalogue ([format](flicks/data/README.md)) |
| `--voice-model DIR` | none | Local Whisper model for speech ([voice setup](docs/voice.md)) |
| `--llm-url URL` | none | Experimental: a local model server instead of the built-in model ([ADR 0013](docs/adr/0013-local-llm.md)) |

## How it works

```
Browser (React)  ──HTTP──▶  FastAPI on 127.0.0.1  ──▶  recommender · Ask readers · language model (optional)
                                                      · repositories (SQLite) · media library
Phones on Wi-Fi  ──HTTP──▶  couch guest server (only during a session, couch routes only)
```

The server binds to loopback, so the app is reachable only from this machine. Couch mode is the one
opt-in exception, and it runs as a separate server with no access to your data. Security rules (Host and
Origin checks, JSON-only requests, size limits, a strict Content Security Policy) are enforced in one
place and covered by tests.

See [architecture](docs/architecture.md) for the components, the ranking model and the API, and the
[architecture decision records](docs/adr/README.md) for why Flicks is built the way it is.

## Project layout

```
flicks/            Python package: recommender, API, storage, media, Discover, couch mode, assistants
  api/             FastAPI apps, routes and the request guard
  assistant/       Ask rules, the Ask student, the title chat, the corner chat, the language model runtime
  data/            Bundled demo catalogue and the Ask student's weights
  datasets/        MovieLens, TVmaze, trailer and Internet Archive importers, neighbours, evaluation
  setup.py         `flicks setup`
web/               React + TypeScript interface (built into flicks/static/)
tests/             Backend tests (pytest)
scripts/           Voice-model download and icon generation
docs/              Architecture, decision records, feature guides, evaluation
```

## Development

From a clone, with Python 3.10+ and Node 20+:

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
npm --prefix web ci
npm --prefix web run build      # the interface, into flicks/static/ (not committed)
.venv/bin/flicks setup          # optional: the full catalogues
.venv/bin/flicks
```

On Windows, use `.venv\Scripts\pip` and `.venv\Scripts\flicks`. For live reloading, run the API and the
interface dev server side by side:

```sh
.venv/bin/flicks --dev
npm --prefix web run dev        # http://localhost:5173
```

Checks (CI runs them on every push, with the Python tests on Linux, Windows and macOS):

```sh
.venv/bin/python -m pytest
.venv/bin/ruff check flicks tests scripts
npm --prefix web run lint
npm --prefix web test
npm --prefix web run build
npm --prefix web run test:e2e   # Playwright, Chromium and WebKit (first: npx --prefix web playwright install chromium webkit)
```

Measurements (not run in CI; results are in [docs/test-report.md](docs/test-report.md)):

```sh
.venv/bin/python -m flicks.benchmark                     # latency and memory
.venv/bin/python -m flicks.datasets.evaluation           # recommendation quality on held-out MovieLens ratings
.venv/bin/python -m flicks.datasets.ask --evaluate-only  # the Ask student on its held-out test set
.venv/bin/python -m flicks.assistant.agent_eval --no-llm # the Ask pipeline on hard cases
.venv/bin/python -m flicks.assistant.title_chat_eval ~/.flicks/models/Qwen3.5-2B-Q4_K_M.gguf  # the title chat, scored by hand
```

**Releasing.** Bump `version` in `pyproject.toml`, merge, then tag the merge commit `v<version>` and push the
tag. The release workflow builds the interface and the wheel, checks the wheel, and publishes both to
GitHub Releases ([ADR 0020](docs/adr/0020-packaging.md)). Update the version in the install line above.

## Documentation

| Document | Contents |
|---|---|
| [Architecture](docs/architecture.md) | Components, data flow, security model, ranking model, API |
| [Test report](docs/test-report.md) | Latest test, latency and AI evaluation results, with what they mean |
| [Decision records](docs/adr/README.md) | Why the project is built the way it is |
| [Voice commands](docs/voice.md) | On-device speech setup and the supported commands |
| [Couch mode](docs/couch.md) | Joining, voting, the remote, and what is guaranteed |
| [System One](docs/system-one.md) | Typed-decision models for tagging and command fallback |
| [Evaluation](docs/evaluation.md) | What has been verified, measured results, and the evaluation plan |
| [Catalogue format](flicks/data/README.md) | The demo catalogue and how to bring your own |
| [Proposal](docs/proposal.md) | The original project proposal |
