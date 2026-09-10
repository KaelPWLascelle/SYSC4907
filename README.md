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
