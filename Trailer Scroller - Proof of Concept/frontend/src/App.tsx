import React, { useRef, useState, useEffect, useCallback } from "react";
import MovieCard from "./components/MovieCard";
import { useMovies, useStats } from "./hooks/useApi";
import "./App.css";

export default function App() {
  const { movies, total, loading, loadingMore, error, loadMore } = useMovies();
  const stats = useStats();
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Track active card via IntersectionObserver
  useEffect(() => {
    const container = containerRef.current;
    if (!container || movies.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const idx = Number((entry.target as HTMLElement).dataset.index);
            if (!isNaN(idx)) setActiveIndex(idx);
          }
        });
      },
      { threshold: 0.6 }
    );

    container.querySelectorAll(".movie-slide").forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [movies]);

  // Load more when sentinel comes into view
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMore(); },
      { threshold: 0.1 }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore]);

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loader" />
        <p>Loading your local library…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-screen">
        <div className="error-icon">⚠</div>
        <h2>Cannot connect to backend</h2>
        <p>{error}</p>
        <div className="error-steps">
          <p>Make sure the backend is running:</p>
          <code>python -m uvicorn main:app --port 8000</code>
          <p>And setup has been run:</p>
          <code>python setup.py --token YOUR_TOKEN</code>
        </div>
      </div>
    );
  }

  if (movies.length === 0) {
    return (
      <div className="error-screen">
        <div className="error-icon">🎬</div>
        <h2>No movies found</h2>
        <p>Run the setup script to download trailers:</p>
        <code>python setup.py --token YOUR_TMDB_TOKEN --movies 50</code>
      </div>
    );
  }

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <span className="logo">🎬 LocalScroll</span>
        <div className="header-right">
          {stats && (
            <span className="stats-pill">
              {stats.total_movies} films · {stats.liked} liked
            </span>
          )}
          <span className="counter">{activeIndex + 1} / {total}</span>
        </div>
      </header>

      {/* Scroll feed */}
      <div className="scroll-container" ref={containerRef}>
        {movies.map((movie, i) => (
          <div key={movie.id} className="movie-slide" data-index={i}>
            <MovieCard movie={movie} isActive={i === activeIndex} />
          </div>
        ))}

        {/* Infinite scroll sentinel */}
        <div ref={sentinelRef} className="sentinel">
          {loadingMore && <div className="loader-sm" />}
        </div>
      </div>
    </div>
  );
}
