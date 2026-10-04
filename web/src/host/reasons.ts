import type { Recommendation, Session } from '../api/types';
import { capitalize, runtime } from '../lib/format';

/** Factor weights from flicks/core.py (HeuristicDecision). A factor at its weight is a full match. */
export const FACTORS: Record<string, { label: string; max: number }> = {
  taste: { label: 'Your taste', max: 0.55 },
  mood: { label: 'Mood', max: 0.2 },
  intensity: { label: 'Intensity', max: 0.15 },
  novelty: { label: 'Discovery', max: 0.1 },
};

/**
 * Plain-language reasons, derived from the factors that actually produced the score
 * (not from editorial labels), so the chips never claim something the ranking did not use.
 */
export function reasons(row: Recommendation, session: Session): string[] {
  const { content, factors, evidence } = row;
  const list: string[] = [];
  if (session.mood !== 'any' && (factors.mood ?? 0) >= 0.19) list.push(`${capitalize(session.mood)} mood`);
  if ((factors.intensity ?? 0) >= 0.135) {
    list.push(content.intensity < 0.35 ? 'Easygoing' : content.intensity > 0.65 ? 'Full throttle' : 'Right intensity');
  }
  if (evidence.length) list.push(`Your taste: ${evidence.slice(0, 2).join(' · ')}`);
  list.push(`${runtime(content.minutes)} · fits ${runtime(session.minutes)}`);
  return list;
}
