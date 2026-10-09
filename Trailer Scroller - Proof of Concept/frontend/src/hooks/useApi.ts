import { useState, useEffect, useCallback, useRef } from "react";
import { Movie, Reaction, ReactionResponse, MoviesResponse, Stats } from "../types";

const API = "http://localhost:8000";
const PAGE_SIZE = 20;

// ── Movies with infinite scroll ────────────────────────────────────────────────

export function useMovies() {
  const [movies, setMovies] = useState<Movie[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const offset = useRef(0);

  const fetchPage = useCallback(async (reset = false) => {
    const currentOffset = reset ? 0 : offset.current;
    if (!reset && currentOffset >= total && total > 0) return;

    reset ? setLoading(true) : setLoadingMore(true);

    try {
      const res = await fetch(`${API}/movies?limit=${PAGE_SIZE}&offset=${currentOffset}`);
      if (!res.ok) throw new Error(await res.text());
      const data: MoviesResponse = await res.json();
      setTotal(data.total);
      setMovies((prev) => reset ? data.movies : [...prev, ...data.movies]);
      offset.current = currentOffset + data.movies.length;
    } catch (e: any) {
      setError(e.message ?? "Failed to load movies");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [total]);

  useEffect(() => { fetchPage(true); }, []);

  const loadMore = useCallback(() => {
    if (!loadingMore && movies.length < total) fetchPage();
  }, [loadingMore, movies.length, total, fetchPage]);

  return { movies, total, loading, loadingMore, error, loadMore };
}

// ── Per-card reaction + progress ───────────────────────────────────────────────

export function useMovieCard(initial: Movie) {
  const [likes, setLikes] = useState(initial.likes);
  const [dislikes, setDislikes] = useState(initial.dislikes);
  const [reaction, setReaction] = useState<Reaction>(initial.reaction);
  const busy = useRef(false);
  const progressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const react = useCallback(async (r: Reaction) => {
    if (busy.current) return;
    const next: Reaction = reaction === r ? null : r;

    // Optimistic update
    setLikes((l) => {
      let n = l;
      if (reaction === "like") n = Math.max(0, n - 1);
      if (next === "like") n += 1;
      return n;
    });
    setDislikes((d) => {
      let n = d;
      if (reaction === "dislike") n = Math.max(0, n - 1);
      if (next === "dislike") n += 1;
      return n;
    });
    setReaction(next);

    busy.current = true;
    try {
      const res = await fetch(`${API}/movies/${initial.id}/react`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reaction: next }),
      });
      if (!res.ok) throw new Error();
      const data: ReactionResponse = await res.json();
      setLikes(data.likes);
      setDislikes(data.dislikes);
      setReaction(data.reaction);
    } catch {
      // Revert
      setLikes(initial.likes);
      setDislikes(initial.dislikes);
      setReaction(initial.reaction);
    } finally {
      busy.current = false;
    }
  }, [reaction, initial]);

  // Debounced progress save — fires 2s after last update
  const saveProgress = useCallback((seconds: number) => {
    if (progressTimer.current) clearTimeout(progressTimer.current);
    progressTimer.current = setTimeout(() => {
      fetch(`${API}/movies/${initial.id}/progress`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ progress_s: seconds }),
      }).catch(() => {});
    }, 2000);
  }, [initial.id]);

  return { likes, dislikes, reaction, react, saveProgress };
}

// ── Stats ──────────────────────────────────────────────────────────────────────

export function useStats() {
  const [stats, setStats] = useState<Stats | null>(null);
  useEffect(() => {
    fetch(`${API}/stats`)
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {});
  }, []);
  return stats;
}
