"""
LocalScroll Setup Script
------------------------
Run this once to:
1. Fetch movie metadata from TMDB and store in local SQLite DB
2. Download trailer videos via yt-dlp to /videos/
3. Download poster images to /posters/

Usage:
    python setup.py --token YOUR_TMDB_READ_ACCESS_TOKEN --movies 50
"""

import argparse
import sqlite3
import os
import sys
import time
import urllib.request
import json
import subprocess
import shutil

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "localscroll.db")


def get_ytdlp_cmd():
    """Return the best available yt-dlp invocation, or None if not found."""
    # 1. Standalone yt-dlp.exe in the backend folder
    local_exe = os.path.join(os.path.dirname(__file__), "yt-dlp.exe")
    if os.path.exists(local_exe):
        return [local_exe]
    # 2. yt-dlp on PATH
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    # 3. python -m yt_dlp (works when installed but not on PATH)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True, timeout=10
        )
        if result.returncode == 0:
            return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        pass
    return None
VIDEOS_DIR = os.path.join(os.path.dirname(__file__), "videos")
POSTERS_DIR = os.path.join(os.path.dirname(__file__), "posters")
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w780"


# ── Database setup ─────────────────────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS movies (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            year        INTEGER,
            genre       TEXT,
            rating      TEXT,
            description TEXT,
            youtube_id  TEXT,
            poster_file TEXT,
            video_file  TEXT,
            likes       INTEGER DEFAULT 0,
            dislikes    INTEGER DEFAULT 0,
            downloaded  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS reactions (
            movie_id    TEXT NOT NULL,
            reaction    TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (movie_id)
        );

        CREATE TABLE IF NOT EXISTS watch_history (
            movie_id    TEXT NOT NULL,
            watched_at  TEXT DEFAULT (datetime('now')),
            progress_s  REAL DEFAULT 0,
            PRIMARY KEY (movie_id)
        );
    """)
    conn.commit()
    return conn


# ── TMDB helpers ───────────────────────────────────────────────────────────────

def tmdb_get(path: str, token: str, params: dict = {}) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{TMDB_BASE}{path}?{query}" if query else f"{TMDB_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_genre_map(token: str) -> dict:
    data = tmdb_get("/genre/movie/list", token)
    return {g["id"]: g["name"] for g in data.get("genres", [])}


def get_movies(token: str, count: int) -> list[dict]:
    movies = []
    page = 1
    while len(movies) < count:
        data = tmdb_get("/movie/popular", token, {"page": page, "language": "en-US"})
        movies.extend(data.get("results", []))
        if page >= data.get("total_pages", 1):
            break
        page += 1
        time.sleep(0.25)
    return movies[:count]


def get_trailer_key(movie_id: int, token: str) -> str | None:
    data = tmdb_get(f"/movie/{movie_id}/videos", token, {"language": "en-US"})
    videos = data.get("results", [])
    # Prefer official trailers, fall back to any trailer, then teaser
    for vtype in ("Trailer", "Teaser"):
        match = next(
            (v for v in videos if v["site"] == "YouTube" and v["type"] == vtype and v.get("official", False)),
            None
        ) or next(
            (v for v in videos if v["site"] == "YouTube" and v["type"] == vtype),
            None
        )
        if match:
            return match["key"]
    return None


def get_certification(movie_id: int, token: str) -> str:
    try:
        data = tmdb_get(f"/movie/{movie_id}/release_dates", token)
        for result in data.get("results", []):
            if result["iso_3166_1"] == "US":
                for rd in result.get("release_dates", []):
                    cert = rd.get("certification", "").strip()
                    if cert:
                        return cert
    except Exception:
        pass
    return "NR"


# ── Downloaders ────────────────────────────────────────────────────────────────

def download_poster(movie_id: str, poster_path: str) -> str | None:
    if not poster_path:
        return None
    os.makedirs(POSTERS_DIR, exist_ok=True)
    dest = os.path.join(POSTERS_DIR, f"{movie_id}.jpg")
    if os.path.exists(dest):
        return f"{movie_id}.jpg"
    try:
        url = f"{TMDB_IMAGE_BASE}{poster_path}"
        urllib.request.urlretrieve(url, dest)
        return f"{movie_id}.jpg"
    except Exception as e:
        print(f"    ⚠ Poster download failed: {e}")
        return None


def download_video(movie_id: str, youtube_key: str) -> str | None:
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    dest = os.path.join(VIDEOS_DIR, f"{movie_id}.mp4")
    if os.path.exists(dest):
        print(f"    ✓ Video already exists, skipping")
        return f"{movie_id}.mp4"

    cmd = get_ytdlp_cmd()
    if cmd is None:
        print("    ⚠ yt-dlp not found. Install with: pip install yt-dlp")
        return None

    url = f"https://www.youtube.com/watch?v={youtube_key}"
    try:
        result = subprocess.run(cmd + [
            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
            "--merge-output-format", "mp4",
            "-o", dest,
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            url
        ], capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and os.path.exists(dest):
            size_mb = os.path.getsize(dest) / 1024 / 1024
            print(f"    ✓ Downloaded ({size_mb:.1f} MB)")
            return f"{movie_id}.mp4"
        else:
            print(f"    ⚠ yt-dlp failed: {result.stderr.strip()[:100]}")
            return None
    except subprocess.TimeoutExpired:
        print("    ⚠ Download timed out")
        return None
    except Exception as e:
        print(f"    ⚠ Download error: {e}")
        return None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LocalScroll one-time setup")
    parser.add_argument("--token", required=True, help="TMDB API Read Access Token")
    parser.add_argument("--movies", type=int, default=50, help="Number of movies to fetch (default: 50)")
    parser.add_argument("--skip-video", action="store_true", help="Skip video downloads (metadata + posters only)")
    args = parser.parse_args()

    print("\n🎬 LocalScroll Setup\n" + "─" * 40)

    # Verify yt-dlp if we need it
    if not args.skip_video and get_ytdlp_cmd() is None:
        print("⚠  yt-dlp is not installed. Install it first:\n")
        print("   pip install yt-dlp\n")
        print("   Or run with --skip-video to download metadata only.")
        sys.exit(1)

    print(f"📡 Fetching {args.movies} movies from TMDB...")
    try:
        genre_map = get_genre_map(args.token)
        movies = get_movies(args.token, args.movies)
    except Exception as e:
        print(f"✗ TMDB request failed: {e}")
        print("  Check your token and internet connection.")
        sys.exit(1)

    print(f"✓ Got {len(movies)} movies\n")

    conn = init_db()
    c = conn.cursor()

    success = 0
    for i, movie in enumerate(movies):
        title = movie.get("title", "Unknown")
        movie_id = str(movie["id"])
        print(f"[{i+1}/{len(movies)}] {title}")

        # Check if already in DB and downloaded
        existing = c.execute(
            "SELECT downloaded FROM movies WHERE id=?", (movie_id,)
        ).fetchone()
        if existing and existing[0]:
            print("    ✓ Already set up, skipping")
            success += 1
            continue

        # Get trailer YouTube key
        youtube_key = None
        try:
            youtube_key = get_trailer_key(movie["id"], args.token)
            time.sleep(0.15)
        except Exception as e:
            print(f"    ⚠ Could not fetch trailer: {e}")

        if not youtube_key:
            print("    ✗ No YouTube trailer found, skipping")
            continue

        # Get certification
        rating = "NR"
        try:
            rating = get_certification(movie["id"], args.token)
            time.sleep(0.1)
        except Exception:
            pass

        # Download poster
        poster_file = download_poster(movie_id, movie.get("poster_path"))

        # Download video
        video_file = None
        if not args.skip_video:
            print(f"    ↓ Downloading trailer...")
            video_file = download_video(movie_id, youtube_key)

        # Build genre string
        genre_ids = movie.get("genre_ids", [])
        genres = ", ".join(genre_map.get(gid, "") for gid in genre_ids[:3] if gid in genre_map)

        # Save to DB
        year = int(movie.get("release_date", "0000")[:4]) if movie.get("release_date") else 0
        downloaded = 1 if (video_file or args.skip_video) else 0

        c.execute("""
            INSERT OR REPLACE INTO movies
                (id, title, year, genre, rating, description, youtube_id,
                 poster_file, video_file, downloaded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            movie_id, title, year, genres, rating,
            movie.get("overview", ""), youtube_key,
            poster_file, video_file, downloaded
        ))
        conn.commit()
        success += 1
        print(f"    ✓ Saved")

    conn.close()

    print(f"\n{'─'*40}")
    print(f"✅ Setup complete! {success}/{len(movies)} movies ready.")
    print(f"\nDatabase: {DB_PATH}")
    print(f"Videos:   {VIDEOS_DIR}/")
    print(f"Posters:  {POSTERS_DIR}/")
    print(f"\nNow start the server:")
    print(f"  python -m uvicorn main:app --reload --port 8000\n")


if __name__ == "__main__":
    main()