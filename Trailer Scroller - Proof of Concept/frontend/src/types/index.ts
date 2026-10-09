export interface Movie {
  id: string;
  title: string;
  year: number;
  genre: string[];
  rating: string;
  description: string;
  youtube_id: string;
  poster_url: string | null;
  video_url: string | null;
  likes: number;
  dislikes: number;
  reaction: "like" | "dislike" | null;
  progress_s: number | null;
}

export type Reaction = "like" | "dislike" | null;

export interface MoviesResponse {
  total: number;
  offset: number;
  limit: number;
  movies: Movie[];
}

export interface ReactionResponse {
  movie_id: string;
  likes: number;
  dislikes: number;
  reaction: Reaction;
}

export interface Stats {
  total_movies: number;
  liked: number;
  disliked: number;
  watched: number;
}
