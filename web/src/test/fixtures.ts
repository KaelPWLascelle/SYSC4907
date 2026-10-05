import type { AppState, Content, Recommendation } from '../api/types';

export const content = (id: string, title: string, over: Partial<Content> = {}): Content => ({
  id,
  title,
  year: 2000,
  kind: 'movie',
  minutes: 100,
  genres: ['drama'],
  tags: ['quiet'],
  moods: ['relaxing'],
  intensity: 0.3,
  description: `About ${title}`,
  ...over,
});

export const ALPHA = content('m1', 'Alpha');
export const BETA = content('m2', 'Beta', { genres: ['horror'] });
export const GAMMA = content('m3', 'Gamma');
export const CATALOG = [ALPHA, BETA, GAMMA];

export const appState = (over: Partial<AppState> = {}): AppState => ({
  catalog_size: CATALOG.length,
  genres: ['drama', 'horror'],
  feedback: {},
  voice: { available: false, message: 'Voice is not configured.', max_bytes: 5_242_880, max_seconds: 30 },
  assistant: 'Local command rules',
  tagged: false,
  collaborative: false,
  couch: false,
  podcasts: false,
  posters: [],
  media: [{ id: 'm1', direct_play: true, audio: false }],
  ...over,
});

export const pick = (item: Content, score = 0.6): Recommendation => ({
  content: item,
  score,
  factors: { taste: score - 0.3, mood: 0.2, intensity: 0.05, novelty: 0.05 },
  evidence: ['quiet'],
  negative_evidence: [],
  because: [],
  familiarity: null,
});
