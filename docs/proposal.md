# Project proposal

**Development of a Streaming Video Player Integrated with Local AI-Based Movie Recommendation
Considering User Personal Interests**. SYSC 4907 capstone, supervised by Dr. Huang.

This is the proposal the project started from. It is kept as the reference for the project's
objectives. Where the implementation chose differently (for example a local web app rather than
Streamlit or PyQt), the reasons are recorded in the [architecture decision records](adr/README.md).

## Overview

A privacy-focused streaming video player with an on-device AI recommendation engine. The system
analyzes local user interactions (watch history, ratings, and genre preferences) to recommend movies
and videos without requiring cloud processing.

### Problem statement

Current platforms rely heavily on cloud recommendation systems, which can create:

- privacy concerns due to extensive user tracking;
- offline limitations when internet access is unavailable;
- generic recommendations that do not deeply reflect personal interests.

This project addresses these issues through local-first data processing and recommendations.

## Objectives

### Primary objective

Design and implement a streaming video player with an integrated local AI recommendation system that
personalizes suggestions based on user interests.

### Secondary objectives

- Collect and analyze local user data (watch history, ratings, preferences).
- Build recommendation models (content-based and/or collaborative filtering).
- Provide a user-friendly interface for playback, library management, ratings, and recommendations.
- Support offline operation with optional metadata fetching from public APIs.
- Evaluate recommendation quality and performance using metrics such as precision and recall.

## Methodology

### System architecture

- **Video player:** playback for local files (e.g. MP4, MKV) and URL streams.
- **Data management:** local SQLite storage for watch logs, ratings, and preferences.
- **Recommendation engine:** a local ML pipeline using features such as genre similarity, rating
  patterns, and viewing frequency.
- **User interface:** a desktop or web interface for browsing, playback, rating, and recommendations.

### Technologies considered

- **Languages:** Python (primary), JavaScript/HTML for a web interface.
- **Video and media:** VLC/FFmpeg bindings, MoviePy, or OpenCV.
- **AI/ML:** scikit-learn and/or TensorFlow Lite.
- **Data:** SQLite.
- **UI:** Streamlit, PyQt, Tkinter, or Electron.
- **Workflow:** Jupyter for prototyping, Git for version control.

## Expected outcomes

- A cross-platform application (Windows, Linux, macOS).
- Personalized recommendation demonstrations (e.g. action and drama preference profiles).
- Target metrics: recommendation hit rate above 70%, playback latency under 2 seconds.
- An open-source codebase with implementation and usage guidance.
- A final report covering architecture, evaluation, and future expansion opportunities.

## Budget and resources

- Low-cost implementation using open-source tools and free or public datasets (e.g. MovieLens).
- Optional metadata APIs (e.g. the TMDB free tier).
- A team of 3–4 contributors with roles across AI, frontend, and testing.
