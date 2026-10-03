# SYSC4907

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

## Kevin recommendation MVP

Kevin v0.3 is a working, local-first experiment for the recommendation concept.
It includes a browser UI, 36 bundled movie/short-film records, like/dislike/clear
controls, SQLite feedback persistence, a TF-IDF taste profile, and a separate
explainable session reranker. No API keys, model downloads, or third-party Python
packages are required. Optional local Whisper voice commands are available; playback and eye tracking remain future work.

### Run

Requires Python 3.10+ and a modern browser. From the repository root:

```sh
python3 -m kevin
```

On Windows, use `py -3 -m kevin`. Open <http://127.0.0.1:8765>.
To install it as a `kevin` command instead (still no third-party dependencies), run
`python3 -m pip install .` from the repository, then `kevin`.
Stop with Ctrl+C. Feedback survives restarts in `~/.kevin/feedback.sqlite3`.
For a separate demo profile or a different port:

```sh
python3 -m kevin --db .local/demo.sqlite3 --port 8766
```

All computation and data stay on the machine running Python. Open the browser
on that same machine; the server deliberately binds only to loopback. The one
exception is opt-in [couch mode](docs/couch.md), which opens a separate,
couch-only server on your home network while a session runs. Once the
repository and Python are present, the demo works without internet access.

### Try the concept

1. Like **Arrival** and **Moon**, then dislike **Alien** in the catalogue.
2. Set 120 minutes, Curious, medium intensity, and low Discovery. Generate picks.
3. Change to Relaxing and low intensity, then generate again.
4. Switch between **Taste only · baseline** and **Taste + this session** to compare.
5. Open **Why this pick?** for weighted contributions and matching profile terms.
6. Try 45 minutes for short films or 10 minutes for the explicit empty state.
7. Reload or restart: your ratings remain. Use **Clear** to undo an individual rating.

To start completely fresh without deleting anything, supply a new `--db` path.
Session controls are intentionally temporary and return to defaults on reload.

### Voice commands and typed assistant

The **Just ask Kevin** panel accepts typed requests such as “relaxing, 90 minutes,
no horror” and “Like Arrival”. Preview the proposed changes, then Apply. Genre
exclusions are hard constraints in both ranking modes.

For local microphone transcription and audio-file uploads, follow
[the voice setup and command guide](docs/voice.md). This adds optional
faster-whisper dependencies and an explicitly downloaded model. Recordings stay
on-device and are not saved by Kevin. No cloud speech API or wake word is used.

### Couch mode (prototype)

Start Kevin with `--couch` and press **Start a couch session**. Phones on the same Wi-Fi scan the QR
code, vote on a shortlist with hidden votes, and act as a remote. Guests reach a separate
local-network server that exposes only couch routes. Your ratings and history are never reachable
from the network, and names and votes are forgotten when the session ends. See
[how couch mode works and what it guarantees](docs/couch.md).

### System One models (experimental)

Kevin can ask a System One decision model (Laya, Kev, or TypeSafe's Jev) typed questions:
tag the catalogue at build time from public text only, fall back to a **local** model for free-text
commands the rules do not understand, and distil the teacher into a small student that also runs
in the browser. User text is never sent to a non-local backend; the code refuses it.

```sh
python3 -m kevin.tagging --out work/tags.json
python3 -m kevin.distill --tags work/tags.json --export-laya work/laya-data --student work/student.json
python3 -m kevin --tags work/tags.json --system-one-url lexical
```

These commands use an offline keyword stand-in (not a model). See
[System One design, privacy rules, results and next steps](docs/system-one.md) for running Laya
locally, Jev for catalogue-only tagging, and the fine-tuning path.

### Verify

```sh
python3 -m unittest discover -s tests -v
python3 -m kevin.evaluate
# Optional frontend state tests (Node 24):
node --test tests/voice-ui.test.mjs tests/student.test.mjs tests/couch-ui.test.mjs
```

Tests exercise ranking behavior, time constraints, negative feedback, cold start,
explanations, validation, persistence, adapter injection, and real HTTP requests.
CI is configured for Python 3.10/3.12 on Linux, Windows, and macOS.

See [architecture and scoring](docs/architecture.md),
[data provenance and schema](kevin/data/README.md), and
[validation, limitations, and next iteration](docs/validation.md).
