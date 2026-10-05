/** Shapes of the Flicks HTTP API. Mirrors the Python responses (flicks/api); keep the two in step. */

export const MOODS = ['any', 'relaxing', 'uplifting', 'curious', 'tense', 'reflective'] as const;
export type Mood = (typeof MOODS)[number];
export type Mode = 'session' | 'baseline';
export type Rating = 1 | -1;

export interface Content {
  id: string;
  title: string;
  year: number;
  kind: string;
  minutes: number;
  genres: string[];
  tags: string[];
  moods: Exclude<Mood, 'any'>[];
  intensity: number;
  description: string;
}

export interface VoiceStatus {
  available: boolean;
  message: string;
  max_bytes: number;
  max_seconds: number;
}

export interface MediaEntry {
  id: string;
  /** False for containers some browsers cannot play (MKV, MOV). */
  direct_play: boolean;
}

/** A title the player and couch remote can refer to; Content and CouchItem both satisfy it. */
export interface TitleRef {
  id: string;
  title: string;
}

export interface AppState {
  /** The catalogue itself is not sent (it can hold thousands of titles); search it with /api/titles. */
  catalog_size: number;
  genres: string[];
  feedback: Record<string, Rating>;
  voice: VoiceStatus;
  assistant: string;
  tagged: boolean;
  /** Recommendations also use public ratings (item-to-item collaborative filtering). */
  collaborative: boolean;
  couch: boolean;
  posters: string[];
  media: MediaEntry[];
}

export interface Session {
  mood: Mood;
  minutes: number;
  intensity: number;
  novelty: number;
  excluded_genres: string[];
}

export interface Recommendation {
  content: Content;
  /** A ranking signal in [0, 1], not a probability. Factors sum to it. */
  score: number;
  factors: Record<string, number>;
  evidence: string[];
  negative_evidence: string[];
  /** Liked titles whose fans also liked this one (collaborative filtering), strongest first. */
  because: string[];
  familiarity: number | null;
}

export interface RecommendResponse {
  recommendations: Recommendation[];
  cold_start: boolean;
}

export interface Command {
  intent: 'feedback' | 'session' | 'unknown';
  summary: string;
  note?: string;
  id?: string;
  value?: number;
  patch?: Partial<Session>;
}

export interface CommandResponse {
  command: Command;
  session: Session;
  feedback: Record<string, Rating>;
}

export interface TranscribeResponse {
  text: string;
  seconds: number;
  processing_ms: number;
}

export interface Progress {
  content_id: string;
  position_seconds: number;
  duration_seconds: number;
  completed: boolean;
  updated_at: string;
  /** Not finished and watched long enough to offer "continue watching". */
  resumable: boolean;
  content: Content;
}

export type TitleFilter = 'all' | 'liked' | 'passed' | 'unrated';

export interface TitlesResponse {
  items: Content[];
  total: number;
}

// ---------- couch mode ----------

export type PlayerAction = 'play' | 'pause' | 'stop' | 'select';

export interface PlayerState {
  id: string | null;
  state: 'playing' | 'paused' | 'stopped';
  by: string | null;
}

export interface CouchItem {
  id: string;
  title: string;
  year: number;
  minutes: number;
  genres: string[];
  moods: string[];
  intensity: number;
  description: string;
  poster: boolean;
}

export interface CouchResult {
  id: string;
  yes: number;
  no: number;
  flicks_rank: number;
  match: boolean;
}

export interface CouchProgress {
  name: string;
  voted: number;
  total: number;
}

export interface CouchCommon {
  active: true;
  version: number;
  items: CouchItem[];
  revealed: boolean;
  player: PlayerState;
  expires_in: number;
  progress: CouchProgress[];
  results: CouchResult[] | null;
}

export type CouchHostView = { active: false } | (CouchCommon & { code: string; url: string; join_url: string });

export interface CouchGuestView extends CouchCommon {
  you: { id: string; name: string; votes: Record<string, Rating> };
}
