"""
LocalScroll Backend
-------------------
Fully local FastAPI server. No external calls during operation.
Serves video and poster files from disk, reads/writes SQLite only.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "data", "localscroll.db")
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")
POSTERS_DIR = os.path.join(BASE_DIR, "posters")

app = FastAPI(title="LocalScroll — Private Movie Trailer Browser")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve local video and poster files as static assets
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(POSTERS_DIR, exist_ok=True)
app.mount("/videos", StaticFiles(directory=VIDEOS_DIR), name="videos")
app.mount("/posters", StaticFiles(directory=POSTERS_DIR), name="posters")


# ── DB helpers ─────────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def row_to_movie(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["genre"] = [g.strip() for g in (d.get("genre") or "").split(",") if g.strip()]
    d["poster_url"] = f"/posters/{d['poster_file']}" if d.get("poster_file") else None
    d["video_url"] = f"/videos/{d['video_file']}" if d.get("video_file") else None
    return d


# ── Models ─────────────────────────────────────────────────────────────────────

class ReactionRequest(BaseModel):
    reaction: Optional[str] = None  # "like" | "dislike" | null


class ProgressRequest(BaseModel):
    progress_s: float


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/movies")
def list_movies(limit: int = 50, offset: int = 0):
    """Return paginated list of movies that have been set up."""
    if not os.path.exists(DB_PATH):
        raise HTTPException(
            status_code=503,
            detail="Database not found. Run setup.py first."
        )
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT m.*, r.reaction, w.progress_s
            FROM movies m
            LEFT JOIN reactions r ON r.movie_id = m.id
            LEFT JOIN watch_history w ON w.movie_id = m.id
            WHERE m.video_file IS NOT NULL
            ORDER BY m.title
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM movies WHERE video_file IS NOT NULL"
        ).fetchone()[0]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "movies": [row_to_movie(r) for r in rows],
    }


@app.get("/movies/{movie_id}")
def get_movie(movie_id: str):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT m.*, r.reaction, w.progress_s
            FROM movies m
            LEFT JOIN reactions r ON r.movie_id = m.id
            LEFT JOIN watch_history w ON w.movie_id = m.id
            WHERE m.id = ?
            """,
            (movie_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Movie not found")
    return row_to_movie(row)


@app.post("/movies/{movie_id}/react")
def react(movie_id: str, body: ReactionRequest):
    """Like, dislike, or clear reaction. Stored locally in SQLite."""
    with get_db() as conn:
        movie = conn.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")

        # Get current reaction
        current = conn.execute(
            "SELECT reaction FROM reactions WHERE movie_id=?", (movie_id,)
        ).fetchone()
        prev = current["reaction"] if current else None

        # Adjust counts
        if prev == "like":
            conn.execute("UPDATE movies SET likes = MAX(0, likes-1) WHERE id=?", (movie_id,))
        elif prev == "dislike":
            conn.execute("UPDATE movies SET dislikes = MAX(0, dislikes-1) WHERE id=?", (movie_id,))

        if body.reaction == "like":
            conn.execute("UPDATE movies SET likes = likes+1 WHERE id=?", (movie_id,))
        elif body.reaction == "dislike":
            conn.execute("UPDATE movies SET dislikes = dislikes+1 WHERE id=?", (movie_id,))

        # Save reaction
        conn.execute(
            """
            INSERT INTO reactions (movie_id, reaction)
            VALUES (?, ?)
            ON CONFLICT(movie_id) DO UPDATE SET reaction=excluded.reaction
            """,
            (movie_id, body.reaction),
        )
        conn.commit()

        updated = conn.execute("SELECT likes, dislikes FROM movies WHERE id=?", (movie_id,)).fetchone()
        return {
            "movie_id": movie_id,
            "likes": updated["likes"],
            "dislikes": updated["dislikes"],
            "reaction": body.reaction,
        }


@app.post("/movies/{movie_id}/progress")
def save_progress(movie_id: str, body: ProgressRequest):
    """Save playback position so user can resume where they left off."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO watch_history (movie_id, progress_s)
            VALUES (?, ?)
            ON CONFLICT(movie_id) DO UPDATE SET
                progress_s=excluded.progress_s,
                watched_at=datetime('now')
            """,
            (movie_id, body.progress_s),
        )
        conn.commit()
    return {"ok": True}


@app.get("/stats")
def stats():
    """Summary stats for the local library."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM movies WHERE video_file IS NOT NULL").fetchone()[0]
        liked = conn.execute("SELECT COUNT(*) FROM reactions WHERE reaction='like'").fetchone()[0]
        disliked = conn.execute("SELECT COUNT(*) FROM reactions WHERE reaction='dislike'").fetchone()[0]
        watched = conn.execute("SELECT COUNT(*) FROM watch_history WHERE progress_s > 5").fetchone()[0]
    return {
        "total_movies": total,
        "liked": liked,
        "disliked": disliked,
        "watched": watched,
    }
