# Flicks

[![CI](https://github.com/KaelPWLascelle/SYSC4907/actions/workflows/flicks.yml/badge.svg)](https://github.com/KaelPWLascelle/SYSC4907/actions/workflows/flicks.yml)

**A streaming app whose recommendations never leave your device.** Flicks learns your taste from the
films you like and pass on, reads the evening you describe (mood, time, intensity), and explains
every pick. It plays your own video files, remembers where you stopped, and lets everyone on the
couch vote from their phones. No accounts, no cloud, no tracking.

Flicks is a SYSC 4907 capstone project at Carleton University, supervised by Dr. Huang
([project proposal](docs/proposal.md)).

## Features

- **Personal recommendations, computed locally.** A TF-IDF taste profile built from your ratings,
  reranked for the current scene, with every score broken down into its factors.
- **Streaming-style interface.** A top pick for tonight, a ranked rail, continue watching, browse
  and search, and a "why this pick" sheet for any title.
- **Playback of your own files.** MP4 and WebM stream with seeking; progress is saved and resumed.
- **Long-form podcasts.** Episodes from public feeds are recommended alongside films ("Watch",
  "Listen" or either), downloaded only when you ask, and played and resumed locally.
- **Ask Flicks.** Type or say "something relaxing under 90 minutes, no horror" and preview the
  change before it applies. Speech is transcribed on the device by Whisper.
- **Couch mode.** Phones on your Wi-Fi scan a QR code, vote with hidden ballots, and act as a remote
  for the TV.
- **Installable.** Runs in its own window from Chrome or Edge.

## Quick start

You need Python 3.10+ and Node 20+ (Node is only needed to build the interface).

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
npm --prefix web ci
npm --prefix web run build
.venv/bin/flicks
```

Open <http://127.0.0.1:8765>. On Windows, use `.venv\Scripts\pip` and `.venv\Scripts\flicks`.

Ratings and watch progress are stored in `~/.flicks/feedback.sqlite3` and survive restarts. Use
`--db` for a separate profile.

## Using Flicks

### Play your films

```sh
.venv/bin/flicks --media ~/Movies --media /Volumes/Films
```

Name files the way Jellyfin and Plex do, `A Trip to the Moon (1902).mp4` (optionally inside a folder
of the same name), or by content ID (`m033.webm`). MP4 (H.264/AAC) and WebM play in every browser;
MKV and MOV may not, and Flicks says so instead of failing silently. Public-domain films such as
*A Trip to the Moon*, *Sherlock Jr.* and *The General* make good demo material.

### Use the MovieLens catalogue (about 9,700 films)

Flicks ships with a small hand-curated catalogue of 36 films. To browse and get recommendations from
the MovieLens "latest-small" dataset instead:

```sh
.venv/bin/python -m flicks.datasets.movielens
.venv/bin/flicks --catalog ~/.flicks/catalogs/movielens-small.json --db ~/.flicks/movielens.sqlite3
```

The importer downloads MovieLens from GroupLens (verified against its published checksum) and adds
runtimes and short descriptions from Wikidata and Wikipedia, matched by IMDb ID. Only public film
identifiers are sent. It takes several minutes the first time and is cached after that. Moods and
intensity are estimated from genres. MovieLens is for non-commercial research use and must be cited
(Harper & Konstan, 2015); see [the catalogue guide](flicks/data/README.md#movielens).

### Collaborative filtering and evaluation

With the `datasets` extra installed (`.venv/bin/pip install -e ".[dev,datasets]"`), the MovieLens import
also precomputes which films the same people liked (`movielens-small.neighbours.json`). Flicks then
blends those patterns with its content model, entirely on your device ("Fans of *The Empire Strikes
Back* also like this"). To measure recommendation quality on held-out MovieLens ratings:

```sh
.venv/bin/python -m flicks.datasets.evaluation
```

See [evaluation](docs/evaluation.md) for the protocol and results.

### Add podcasts (optional)

```sh
.venv/bin/python -m flicks.datasets.podcasts                       # nine long-form starter shows
.venv/bin/python -m flicks.datasets.podcasts --feed https://example.com/feed.xml   # or your own feeds
```

This reads the feeds (only their URLs are requested) and writes about 400 episodes of 20 minutes or
more to `~/.flicks/catalogs/podcasts.json`, which Flicks then loads automatically. Choose **Listen**
in the scene for something to listen to. An episode is downloaded from its publisher only when you
press **Download episode**, into `~/.flicks/podcasts`, for your own listening; Flicks never alters or
shares it. See [ADR 0010](docs/adr/0010-podcasts.md).

### Add posters (optional)

```sh
.venv/bin/python -m flicks.posters
```

This caches posters for the catalogue from English Wikipedia (about 6 MB, once). Only titles and
years are sent, and only when you run the command. Posters are copyrighted, so they stay in your
local cache and out of git. Without them, Flicks draws title cards.

### Ask Flicks

Press <kbd>/</kbd> and type a request, or record one if voice is set up. Flicks shows exactly what it
understood (mood, time limit, genres to avoid, or a rating) and changes nothing until you press
Apply. See [voice commands](docs/voice.md) to enable on-device speech.

### Couch mode

```sh
.venv/bin/flicks --couch
```

Press **Start a couch session**. Phones on the same Wi-Fi scan the QR code, swipe through a shortlist
built from your scene, and the group pick appears on the TV. Any phone can then play, pause or stop
the film. Guests reach a separate server that cannot see your ratings or history, and names and
votes are forgotten when the session ends. See [how couch mode works](docs/couch.md).

### Command-line options

| Option | Default | Purpose |
|---|---|---|
| `--media DIR` | none | Folder of video files to play; repeat for more folders |
| `--db FILE` | `~/.flicks/feedback.sqlite3` | Ratings and watch history |
| `--port N` | `8765` | Local port for the app |
| `--posters DIR` | `~/.flicks/posters` | Poster cache from `python -m flicks.posters` |
| `--couch` | off | Allow couch sessions on your home network |
| `--couch-host ADDR` | detected | Home-network address phones connect to |
| `--couch-port N` | `8770` | Port for the couch guest server |
| `--voice-model DIR` | none | Local Whisper model for speech ([voice setup](docs/voice.md)) |
| `--tags FILE` | none | System One catalogue tags ([System One](docs/system-one.md)) |
| `--system-one-url URL` | none | Local System One server for free-text requests |
| `--catalog FILE` | bundled | Your own catalogue ([format](flicks/data/README.md)) |
| `--podcasts FILE` | `~/.flicks/catalogs/podcasts.json` if present | Podcast catalogue from `python -m flicks.datasets.podcasts` |
| `--podcast-downloads DIR` | `~/.flicks/podcasts` | Where downloaded episodes are kept |
| `--dev` | off | Accept requests from the Vite dev server |

## How it works

```
Browser (React)  ──HTTP──▶  FastAPI on 127.0.0.1  ──▶  recommender · repositories (SQLite) · media library
Phones on Wi-Fi  ──HTTP──▶  couch guest server (only during a session, couch routes only)
```

The server binds to loopback, so the app is reachable only from this machine. Couch mode is the one
opt-in exception, and it runs as a separate server with no access to your data. The only remote
request the running app makes is downloading a podcast episode you asked for. Security rules
(Host and Origin checks, JSON-only requests, size limits, a strict Content Security Policy) are
enforced in one place and covered by tests.

See [architecture](docs/architecture.md) for the components, the ranking model and the API, and the
[architecture decision records](docs/adr/README.md) for why the stack is FastAPI, SQLite and React.

## Project layout

```
flicks/            Python package: recommender, API, storage, media, podcasts, couch mode, voice, System One
  api/             FastAPI apps, routes and the request guard
  data/            Bundled demo catalogue
  datasets/        MovieLens and podcast importers, neighbours, offline evaluation
web/               React + TypeScript interface (built into flicks/static/)
tests/             Backend tests (pytest)
scripts/           Voice-model download and icon generation
docs/              Architecture, decision records, feature guides, evaluation
```

## Development

Run the API and the interface dev server side by side; changes reload instantly:

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
```

`flicks/static/` is build output and is not committed.

## Documentation

| Document | Contents |
|---|---|
| [Architecture](docs/architecture.md) | Components, data flow, security model, ranking model, API |
| [Decision records](docs/adr/README.md) | Why the project is built the way it is |
| [Voice commands](docs/voice.md) | On-device speech setup and the supported commands |
| [Couch mode](docs/couch.md) | Joining, voting, the remote, and what is guaranteed |
| [System One](docs/system-one.md) | Typed-decision models for tagging and command fallback |
| [Evaluation](docs/evaluation.md) | What has been verified, measured results, and the evaluation plan |
| [Catalogue format](flicks/data/README.md) | The demo catalogue and how to bring your own |
| [Proposal](docs/proposal.md) | The original project proposal |
