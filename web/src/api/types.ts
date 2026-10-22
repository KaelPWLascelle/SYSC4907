/** Shapes of the Flicks HTTP API. Mirrors the Python responses (flicks/api); keep the two in step. */

export const MOODS = ['any', 'relaxing', 'uplifting', 'curious', 'tense', 'reflective'] as const;
export type Mood = (typeof MOODS)[number];
export type Mode = 'session' | 'baseline';
export type Rating = 1 | -1;
/** What the scene asks for: films, TV series or either (docs/adr/0018-tv-series.md). */
export type Kind = 'any' | 'films' | 'series';

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
  /** Set for TV series only (`kind` "series"); `minutes` is then one episode's typical length. */
  series?: SeriesInfo | null;
}

export interface SeriesInfo {
  seasons: number;
  episodes: number;
  /** The year it last aired; null while it is still running. */
  ended: number | null;
  network: string | null;
  /** Its TVmaze page, where the description comes from (CC BY-SA). */
  page: string;
  /** IMDb votes: how widely watched it is. */
  votes: number;
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
  /** Plays from elsewhere through Flicks (the Internet Archive) rather than from this machine. */
  remote: boolean;
  /** Where it comes from, for credit: "Internet Archive"; null for your own files. */
  source: string | null;
  /** The source's page for this title, when there is one. */
  page: string | null;
}

/** A title the player and couch remote can refer to; Content and CouchItem both satisfy it. */
export interface TitleRef {
  id: string;
  title: string;
}

export interface AppState {
  /** The catalogue itself is not sent (it can hold thousands of titles); search it with /api/titles. */
  catalog_size: number;
  /** How many of those titles are TV series (absent from older servers; 0 for films only). */
  series?: number;
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
  /** The profile these ratings and history belong to (absent from older servers). */
  profile?: CurrentProfile;
  /** The optional local language model behind Ask Flicks' agent and narrated explanations. */
  llm?: LlmStatus;
  /** How many films have a trailer the Discover feed can embed (absent from older servers). */
  trailers?: number;
}

export interface CurrentProfile {
  id: number;
  name: string;
  locked: boolean;
  /** Signed in on purpose, rather than using the default profile. */
  chosen: boolean;
  /** How many profiles exist on this device. */
  count: number;
}

export interface LlmStatus {
  available: boolean;
  name: string | null;
  message: string;
}

// ---------- profiles ----------

export interface ProfileSummary {
  id: number;
  name: string;
  /** Has a PIN. */
  locked: boolean;
  created_at: string;
  ratings: number;
}

export interface ProfilesResponse {
  profiles: ProfileSummary[];
  current: { id: number; name: string; locked: boolean } | null;
  chosen: boolean;
}

export interface ImportResult {
  profile: { id: number; name: string };
  ratings: number;
  history: number;
  /** Rows that matched no title in this catalogue. */
  skipped: number;
}

/** One finished question and answer about a title, sent back for follow-up questions. */
export interface AskTurn {
  question: string;
  answer: string;
}

/** A piece of the answer as it is generated, then the checked result. */
export type AskTitleEvent =
  { delta: string } | { done: true; ok: true; answer: string } | { done: true; ok: false; note: string };

export interface ExplainResponse {
  id: string;
  /** Plain words from the local language model, or null: keep the reasons shown. */
  narration: string | null;
  model?: string;
  note: string;
}

export interface Session {
  mood: Mood;
  minutes: number;
  intensity: number;
  novelty: number;
  excluded_genres: string[];
  /** Films, series or either; only offered when the catalogue has series. */
  kind: Kind;
  /** Only titles that can be played right now (a local file or a stream). */
  playable: boolean;
  /** How much each factor counts: [taste, mood, intensity, discovery], summing to 1. */
  mix: Mix;
}

export type Mix = [number, number, number, number];
export const DEFAULT_MIX: Mix = [0.55, 0.2, 0.15, 0.1];

export interface Recommendation {
  content: Content;
  /** A ranking signal in [0, 1], not a probability. Factors sum to it. */
  score: number;
  factors: Record<string, number>;
  evidence: string[];
  negative_evidence: string[];
  /** Liked titles whose fans also liked this one (collaborative filtering), strongest first. */
  because: string[];
  /** Widely liked in public ratings, and that popularity supplied at least half of the taste score. */
  popular: boolean;
  familiarity: number | null;
}

/** What a Discover card can play: a preview of the film itself (a local file or a stream), and a trailer. */
export interface DiscoverMedia {
  kind: 'file' | 'stream' | null;
  /** A YouTube video ID, embedded only once the viewer allows online trailers. */
  trailer: string | null;
}

/** A Discover card: a pick, the stream it came from, and why it is in the feed. */
export interface DiscoverItem extends Recommendation {
  stream: 'for_you' | 'new' | 'wildcard';
  why: string;
  media: DiscoverMedia;
}

export interface DiscoverResponse {
  items: DiscoverItem[];
}

export interface PickResponse {
  pick: Recommendation;
  /** The chance this title had of being drawn. */
  chance: number;
  /** How many titles it was drawn from. */
  pool: number;
}

export type PickPool = 'picks' | 'anything';

export interface RecommendResponse {
  recommendations: Recommendation[];
  cold_start: boolean;
}

export interface Command {
  /** feedback rates a title; session changes the scene; play and search change nothing stored. */
  intent: 'feedback' | 'session' | 'play' | 'search' | 'unknown';
  summary: string;
  note?: string;
  id?: string;
  value?: number;
  patch?: Partial<Session>;
  /** search: everyday-language catalogue search. */
  query?: string;
  /** search: list titles like this one (its ID). */
  similar?: string;
  /** play, or search for similar titles: the title named. */
  content?: Content;
  /** Who read the request: the rules, System One, or the local language model ("llm"). */
  parser?: string;
  /** llm: one sentence from the model about what it chose. */
  reply?: string | null;
  /** llm: what it looked up on the way, e.g. 'Looked up “Arrival”: 1 found'. */
  steps?: string[];
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
  /** What the search understood, in plain words: ["Comedy", "1990s"] or ["Like Alien"]. */
  understood: string[];
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
  kind: string;
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

// ---------- your taste ----------

export interface TasteResponse {
  liked: number;
  passed: number;
  /** affinity in (-1, 1): positive leans toward, negative away; shrunk toward 0 when there are few ratings. */
  genres: { genre: string; liked: number; passed: number; affinity: number }[];
  /** Themes from the content model's profile; weight scaled so the strongest is 1. */
  themes: { liked: { term: string; weight: number }[]; passed: { term: string; weight: number }[] };
  /** Liked films whose fans' ratings (MovieLens) shape the most picks. */
  influences: { title: string; picks: number }[];
}
