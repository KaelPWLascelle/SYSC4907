import type { Session } from '../api/types';

/** The scene a fresh page starts with. Scenes are per visit by design; ratings are what persist. */
export const DEFAULT_SESSION: Session = {
  mood: 'any',
  minutes: 120,
  intensity: 0.5,
  novelty: 0.3,
  excluded_genres: [],
  medium: 'any',
  playable: false,
};
