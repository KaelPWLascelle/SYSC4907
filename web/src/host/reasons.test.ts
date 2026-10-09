import type { Recommendation, Session } from '../api/types';
import { reasons } from './reasons';

const session: Session = {
  mood: 'relaxing',
  minutes: 120,
  intensity: 0.2,
  novelty: 0.3,
  excluded_genres: [],
  medium: 'any',
  playable: false,
};
const row = (
  factors: Record<string, number>,
  evidence: string[] = [],
  intensity = 0.2,
  because: string[] = [],
  popular = false,
): Recommendation => ({
  content: {
    id: 'm1',
    title: 'T',
    year: 2000,
    kind: 'movie',
    minutes: 95,
    genres: [],
    tags: [],
    moods: [],
    intensity,
    description: '',
  },
  score: Object.values(factors).reduce((a, b) => a + b, 0),
  factors,
  evidence,
  negative_evidence: [],
  because,
  popular,
  familiarity: null,
});

test('only claims the factors that scored', () => {
  expect(
    reasons(row({ taste: 0.3, mood: 0.2, intensity: 0.15, novelty: 0.05 }, ['space', 'science', 'quiet']), session),
  ).toEqual(['Relaxing mood', 'Easygoing', 'Your taste: space · science', '1h 35m · fits 2h']);
  expect(reasons(row({ taste: 0.3, mood: 0, intensity: 0.05, novelty: 0.05 }), session)).toEqual(['1h 35m · fits 2h']);
});

test('collaborative evidence leads the reasons', () => {
  const reasonsList = reasons(row({ taste: 0.4 }, [], 0.2, ['Star Wars', 'Alien']), session);
  expect(reasonsList[0]).toBe('Fans of Star Wars also like this');
});

test('says when popularity carried a pick, and only then', () => {
  expect(reasons(row({ taste: 0.5 }, [], 0.5, [], true), session)[0]).toBe('Crowd favourite');
  expect(reasons(row({ taste: 0.5 }, [], 0.5, ['Alien'], true), session).slice(0, 2)).toEqual([
    'Fans of Alien also like this',
    'Crowd favourite',
  ]);
  expect(reasons(row({ taste: 0.5 }), session)).not.toContain('Crowd favourite');
});

test('an open mood never produces a mood reason', () => {
  expect(reasons(row({ mood: 0.2 }), { ...session, mood: 'any' })).not.toContain('Any mood');
});
