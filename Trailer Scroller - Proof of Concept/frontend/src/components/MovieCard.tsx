import React, { useRef, useEffect, useState, useCallback } from "react";
import { Movie } from "../types";
import { useMovieCard } from "../hooks/useApi";

interface Props {
  movie: Movie;
  isActive: boolean;
}

function fmt(n: number): string {
  return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n);
}

function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

export default function MovieCard({ movie, isActive }: Props) {
  const { likes, dislikes, reaction, react, saveProgress } = useMovieCard(movie);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [progress, setProgress] = useState(movie.progress_s ?? 0);
  const [duration, setDuration] = useState(0);
  const [showInfo, setShowInfo] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const controlsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-play / pause based on active state
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (isActive) {
      // Resume from saved position
      if (movie.progress_s && movie.progress_s > 5) {
        v.currentTime = movie.progress_s;
      }
      v.play().then(() => setPlaying(true)).catch(() => {});
    } else {
      v.pause();
      setPlaying(false);
    }
  }, [isActive]);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      v.play().then(() => setPlaying(true)).catch(() => {});
    } else {
      v.pause();
      setPlaying(false);
    }
    flashControls();
  }, []);

  const toggleMute = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
  }, []);

  const flashControls = () => {
    setShowControls(true);
    if (controlsTimer.current) clearTimeout(controlsTimer.current);
    controlsTimer.current = setTimeout(() => setShowControls(false), 2500);
  };

  const onTimeUpdate = () => {
    const v = videoRef.current;
    if (!v) return;
    setProgress(v.currentTime);
    saveProgress(v.currentTime);
  };

  const onLoadedMetadata = () => {
    const v = videoRef.current;
    if (!v) return;
    setDuration(v.duration);
    if (movie.progress_s && movie.progress_s > 5) {
      v.currentTime = movie.progress_s;
    }
  };

  const onScrub = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = videoRef.current;
    if (!v) return;
    const t = parseFloat(e.target.value);
    v.currentTime = t;
    setProgress(t);
  };

  const progressPct = duration > 0 ? (progress / duration) * 100 : 0;

  return (
    <div className="movie-card" onMouseMove={flashControls} onTouchStart={flashControls}>

      {/* ── Video ── */}
      <div className="video-area" onClick={togglePlay}>
        {movie.video_url ? (
          <video
            ref={videoRef}
            src={`http://localhost:8000${movie.video_url}`}
            className="local-video"
            onTimeUpdate={onTimeUpdate}
            onLoadedMetadata={onLoadedMetadata}
            onEnded={() => setPlaying(false)}
            playsInline
            preload="metadata"
          />
        ) : (
          <div className="no-video">No video file found</div>
        )}

        {/* Poster shown before play */}
        {!playing && movie.poster_url && (
          <img
            src={`http://localhost:8000${movie.poster_url}`}
            alt={movie.title}
            className="poster-overlay"
          />
        )}

        {/* Vignette */}
        <div className="vignette" />

        {/* Play/pause indicator */}
        <div className={`play-indicator ${showControls ? "visible" : ""}`}>
          {playing ? (
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
          )}
        </div>
      </div>

      {/* ── Action rail ── */}
      <div className="action-rail">
        <button
          className={`action-btn ${reaction === "like" ? "active-like" : ""}`}
          onClick={() => react("like")}
          aria-label="Like"
        >
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          </svg>
          <span>{fmt(likes)}</span>
        </button>

        <button
          className={`action-btn ${reaction === "dislike" ? "active-dislike" : ""}`}
          onClick={() => react("dislike")}
          aria-label="Dislike"
        >
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47-.14.73v2c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z"/>
          </svg>
          <span>{fmt(dislikes)}</span>
        </button>

        <button className="action-btn" onClick={toggleMute} aria-label="Mute">
          {muted ? (
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 12A4.5 4.5 0 0014 7.97v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0014 7.97v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
          )}
        </button>

        <button className="action-btn info-btn" onClick={() => setShowInfo(v => !v)} aria-label="Info">
          <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
        </button>
      </div>

      {/* ── Bottom metadata ── */}
      <div className="meta-overlay">
        <div className="tags-row">
          {movie.genre.map((g) => <span key={g} className="genre-tag">{g}</span>)}
          {movie.rating && <span className="rating-badge">{movie.rating}</span>}
        </div>
        <h2 className="movie-title">{movie.title}</h2>
        <p className="movie-year">{movie.year}</p>

        {/* Scrubber */}
        {duration > 0 && (
          <div className={`scrubber-row ${showControls ? "visible" : ""}`} onClick={e => e.stopPropagation()}>
            <span className="time-label">{fmtTime(progress)}</span>
            <input
              type="range"
              className="scrubber"
              min={0}
              max={duration}
              step={0.5}
              value={progress}
              onChange={onScrub}
              style={{ "--pct": `${progressPct}%` } as React.CSSProperties}
            />
            <span className="time-label">{fmtTime(duration)}</span>
          </div>
        )}
      </div>

      {/* ── Info panel ── */}
      {showInfo && (
        <div className="info-panel" onClick={() => setShowInfo(false)}>
          <div className="info-content" onClick={e => e.stopPropagation()}>
            <h3>{movie.title}</h3>
            <p className="info-meta">{movie.year} · {movie.rating} · {movie.genre.join(", ")}</p>
            <p className="info-desc">{movie.description}</p>
            <div className="info-stats">
              <span>❤ {fmt(likes)} likes</span>
              <span>👎 {fmt(dislikes)} dislikes</span>
              {movie.progress_s && movie.progress_s > 5 && (
                <span>▶ Resumed at {fmtTime(movie.progress_s)}</span>
              )}
            </div>
            <button className="close-info" onClick={() => setShowInfo(false)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}
