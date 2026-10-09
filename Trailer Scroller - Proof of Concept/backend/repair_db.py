"""
Repair script — merges split video/audio files and updates the database.
Run after placing ffmpeg.exe in the backend folder.

Usage: python repair_db.py
"""
import sqlite3
import os
import subprocess
import sys
import shutil

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "data", "localscroll.db")
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")


def get_ffmpeg():
    # Check local folder first
    local = os.path.join(BASE_DIR, "ffmpeg.exe")
    if os.path.exists(local):
        return local
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    return None


def get_ytdlp_cmd():
    local_exe = os.path.join(BASE_DIR, "yt-dlp.exe")
    if os.path.exists(local_exe):
        return [local_exe]
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
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


def merge_files(movie_id, ffmpeg):
    """Find the split files for a movie and merge them into one mp4."""
    files = os.listdir(VIDEOS_DIR)

    # Find video and audio parts for this movie id
    video_part = next((f for f in files if f.startswith(f"{movie_id}.f") and f.endswith(".mp4")), None)
    audio_part = next((f for f in files if f.startswith(f"{movie_id}.f") and f.endswith(".m4a")), None)
    out_file = os.path.join(VIDEOS_DIR, f"{movie_id}.mp4")

    # If already merged as a clean mp4 (no .fNNN. in name), skip
    clean_mp4 = next((f for f in files if f == f"{movie_id}.mp4"), None)
    if clean_mp4:
        print(f"    ✓ Already merged: {clean_mp4}")
        return f"{movie_id}.mp4"

    if not video_part or not audio_part:
        print(f"    ✗ Could not find both parts. Found: {[f for f in files if f.startswith(movie_id)]}")
        return None

    video_path = os.path.join(VIDEOS_DIR, video_part)
    audio_path = os.path.join(VIDEOS_DIR, audio_part)

    print(f"    Merging {video_part} + {audio_part} → {movie_id}.mp4")
    result = subprocess.run([
        ffmpeg,
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-y",
        out_file
    ], capture_output=True, text=True)

    if result.returncode == 0 and os.path.exists(out_file):
        size_mb = os.path.getsize(out_file) / 1024 / 1024
        print(f"    ✓ Merged ({size_mb:.1f} MB)")
        # Clean up parts
        os.remove(video_path)
        os.remove(audio_path)
        return f"{movie_id}.mp4"
    else:
        print(f"    ✗ Merge failed: {result.stderr[-200:]}")
        return None


def main():
    ffmpeg = get_ffmpeg()
    if not ffmpeg:
        print("❌ ffmpeg.exe not found in backend folder.")
        print("   Download from: https://github.com/BtbN/FFmpeg-Builds/releases")
        print("   Extract ffmpeg.exe and place it in the backend/ folder.")
        sys.exit(1)

    print(f"✓ ffmpeg found: {ffmpeg}")
    print(f"✓ Database: {DB_PATH}\n")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    movies = c.execute("SELECT id, title FROM movies WHERE video_file IS NULL").fetchall()
    print(f"Found {len(movies)} movies with no video_file set.\n")

    fixed = 0
    for movie in movies:
        movie_id = movie["id"]
        print(f"[{movie_id}] {movie['title']}")
        result = merge_files(movie_id, ffmpeg)
        if result:
            c.execute(
                "UPDATE movies SET video_file=?, downloaded=1 WHERE id=?",
                (result, movie_id)
            )
            conn.commit()
            fixed += 1

    conn.close()
    print(f"\n{'─'*40}")
    print(f"✅ Fixed {fixed}/{len(movies)} movies.")
    print("Restart the backend and refresh the browser.")


if __name__ == "__main__":
    main()