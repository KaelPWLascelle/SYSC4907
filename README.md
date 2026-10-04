# Flicks · SYSC 4907

> **Flicks** is the project name going forward (formerly "Kevin"). The Python package, command and UI are all `flicks`; ratings saved under `~/.kevin/` are picked up automatically.

## Project Title
Development of a Streaming Video Player Integrated with Local AI-Based Movie Recommendation Considering User Personal Interests

## Project Overview
This project develops a privacy-focused streaming video player with an on-device AI recommendation engine. The system analyzes local user interactions (watch history, ratings, and genre preferences) to recommend movies and videos without requiring cloud processing.

### Problem Statement
Current platforms rely heavily on cloud recommendation systems, which can create:
- Privacy concerns due to extensive user tracking
- Offline limitations when internet access is unavailable
- Generic recommendations that do not deeply reflect personal interests

This project addresses these issues through local-first data processing and recommendations.

## Objectives

### Primary Objective
Design and implement a streaming video player with an integrated local AI recommendation system that personalizes suggestions based on user interests.

### Secondary Objectives
- Collect and analyze local user data (watch history, ratings, preferences)
- Build recommendation models (content-based and/or collaborative filtering)
- Provide a user-friendly interface for playback, library management, ratings, and recommendations
- Support offline operation with optional metadata fetching from public APIs
- Evaluate recommendation quality and performance using metrics like precision/recall

## Methodology

### System Architecture
- **Video Player Module**: Playback for local files (e.g., MP4, MKV) and URL streams
- **Data Management Module**: Local SQLite storage for watch logs, ratings, and preferences
- **AI Recommendation Engine**: Local ML pipeline using features such as genre similarity, rating patterns, and viewing frequency
- **User Interface**: Desktop/web interface for browsing, playback, rating, and recommended content

### Technologies and Tools
- **Languages**: Python (primary), JavaScript/HTML (if web UI is selected)
- **Video/Media**: VLC/FFmpeg bindings, MoviePy, or OpenCV
- **AI/ML**: scikit-learn and/or TensorFlow Lite
- **Data**: SQLite
- **UI**: Streamlit, PyQt, Tkinter, or Electron
- **Workflow**: Jupyter for prototyping and Git for version control

## Expected Outcomes
- Cross-platform prototype (Windows/Linux/Mac)
- Personalized recommendation demonstrations (e.g., action/drama preference profiles)
- Target metrics: recommendation hit rate >70%, playback latency <2 seconds
- Open-source codebase with implementation and usage guidance
- Final report with architecture, evaluation, and future expansion opportunities

## Budget and Resources
- Low-cost implementation using open-source tools and free/public datasets (e.g., MovieLens)
- Optional metadata API usage (e.g., TMDB free tier)
- Team structure suitable for 3-4 contributors with roles across AI, frontend, and testing
- Academic supervision under Dr. Huang

## Flicks recommendation MVP

Flicks v0.4 is a working, local-first streaming app for the recommendation concept.
It includes a streaming-style web UI (top-pick hero, ranked rail, continue watching, browse grid
and a “why this pick” sheet), 36 bundled movie/short-film records, one-tap like/pass ratings,
playback of your own video files with resume, a TF-IDF taste profile with an explainable scene
reranker, optional local Whisper voice commands, and couch mode for choosing together. No API keys
or accounts; nothing leaves the device. Architecture decisions are recorded in [docs/adr](docs/adr/README.md).

### Set up (once)

Requires Python 3.10+ and, to build the interface, Node 20+. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"        # Flicks + FastAPI/uvicorn + test tools
npm --prefix web ci                      # interface dependencies (developers only)
npm --prefix web run build               # builds the interface into flicks/static/
```

On Windows use `.venv\Scripts\pip` and `.venv\Scripts\flicks`.

### Run

```sh
.venv/bin/flicks                                  # open http://127.0.0.1:8765
.venv/bin/flicks --media ~/Movies                 # play your own files (repeat --media for more folders)
.venv/bin/flicks --db .local/demo.sqlite3 --port 8766   # a separate demo profile
```

Stop with Ctrl+C. Ratings and watch progress survive restarts in `~/.flicks/feedback.sqlite3`
(ratings from before the rename, in `~/.kevin/`, are picked up automatically).

**Playing films.** Point `--media` at folders of video files named like Jellyfin/Plex libraries,
`A Trip to the Moon (1902).mp4` (optionally inside a folder of the same name), or by content ID
(`m033.webm`). MP4 (H.264/AAC) and WebM play in every browser; MKV and MOV may not, and the app
says so. Public-domain films such as *A Trip to the Moon*, *Sherlock Jr.* and *The General* are good
demo material. See [ADR 0005](docs/adr/0005-video-playback.md).

**Posters (optional, one-time).** Without them, Flicks draws title cards. To cache real posters:

```sh
.venv/bin/python -m flicks.posters      # ~6 MB into ~/.flicks/posters; only titles and years are sent, once
```

Posters are looked up on English Wikipedia when you run this command, and never while you browse.
They are copyrighted, so they stay in your local cache and out of git. `posters.json` in the cache
records each image's source page.

**Install as an app.** In Chrome or Edge, use “Install Flicks” in the address bar for its own window
and dock icon ([ADR 0006](docs/adr/0006-installable-app.md)).

All computation and data stay on the machine running Flicks. The server binds only to loopback; the
one exception is opt-in [couch mode](docs/couch.md), which opens a separate, couch-only server on
your home network while a session runs. Once set up, everything works without internet access.

### Develop the interface

Run the API and the Vite dev server side by side; edits reload instantly:

```sh
.venv/bin/flicks --dev            # API on :8765, also accepting the dev server's origin
npm --prefix web run dev          # http://localhost:5173, proxies /api, /posters and /media
```

The interface lives in `web/` (React + TypeScript, [ADR 0004](docs/adr/0004-react-vite-frontend.md));
`flicks/static/` is build output and is not committed.

### Try the concept

1. In **Browse & rate**, like **Arrival** and **Moon**, then pass on **Alien** (tap again to clear).
2. In the scene bar, pick **Curious**, set 2h, medium intensity, and low Discovery. Picks update live.
3. Switch to **Relaxing** and low intensity and watch the hero and the ranked rail change.
4. Flip the **Lens** between **Taste + scene** and **Taste only** to compare.
5. Open any poster, or **Why this pick**, to see the weighted factors and shared taste terms.
6. Try 45 minutes for short films, or 10 minutes for the empty state.
7. Press <kbd>/</kbd> and type “something tense, no horror”, then Preview and Apply.
8. Reload or restart: your ratings remain.

To start completely fresh without deleting anything, supply a new `--db` path.
Session controls are intentionally temporary and return to defaults on reload.

### Voice commands and typed assistant

The **Just ask Flicks** panel accepts typed requests such as “relaxing, 90 minutes,
no horror” and “Like Arrival”. Preview the proposed changes, then Apply. Genre
exclusions are hard constraints in both ranking modes.

For local microphone transcription and audio-file uploads, follow
[the voice setup and command guide](docs/voice.md). This adds optional
faster-whisper dependencies and an explicitly downloaded model. Recordings stay
on-device and are not saved by Flicks. No cloud speech API or wake word is used.

### Couch mode (prototype)

Start Flicks with `--couch` and press **Start a couch session**. Phones on the same Wi-Fi scan the QR
code, vote on a shortlist with hidden votes, and act as a remote. Guests reach a separate
local-network server that exposes only couch routes. Your ratings and history are never reachable
from the network, and names and votes are forgotten when the session ends. See
[how couch mode works and what it guarantees](docs/couch.md).

### System One models (experimental)

Flicks can ask a System One decision model (Laya, Kev, or TypeSafe's Jev) typed questions:
tag the catalogue at build time from public text only, fall back to a **local** model for free-text
commands the rules do not understand, and distil the teacher into a small student that also runs
in the browser. User text is never sent to a non-local backend; the code refuses it.

```sh
.venv/bin/python -m flicks.tagging --out work/tags.json
.venv/bin/python -m flicks.distill --tags work/tags.json --export-laya work/laya-data --student work/student.json
.venv/bin/flicks --tags work/tags.json --system-one-url lexical
```

These commands use an offline keyword stand-in (not a model). See
[System One design, privacy rules, results and next steps](docs/system-one.md) for running Laya
locally, Jev for catalogue-only tagging, and the fine-tuning path.

### Verify

```sh
.venv/bin/python -m pytest                 # backend: API, security rules, migrations, playback, couch
.venv/bin/ruff check flicks tests scripts  # backend lint
npm --prefix web run lint && npm --prefix web test && npm --prefix web run build
.venv/bin/python -m flicks.evaluate        # deterministic ranking demonstration
```

Backend tests cover ranking, explanations, validation, persistence and migrations, the request
guard (host, origin, content type and size), range-request streaming, watch history, and the couch
guest server over a real socket. Interface tests cover the command/voice state machine, the couch
flows (including stale-poll protection), the player, and the main screens. CI runs Python 3.10/3.12
on Linux, Windows and macOS, plus lint, the interface build, and a packaging check.

See [architecture and scoring](docs/architecture.md),
[data provenance and schema](flicks/data/README.md), and
[validation, limitations, and next iteration](docs/validation.md).
