import type { Recommendation, Session } from '../api/types';
import { capitalize, runtime } from '../lib/format';

/** The factors in the order of a session's mix (Session.mix in flicks/core.py), with their labels. */
export const FACTOR_KEYS = ['taste', 'mood', 'intensity', 'novelty'] as const;
export const FACTOR_LABELS: Record<string, string> = {
  taste: 'Your taste',
  mood: 'Mood',
  intensity: 'Intensity',
  novelty: 'Discovery',
};
/** A factor's weight in this scene's mix: a factor at its weight is a full match. */
export const weightOf = (key: string, session: Session) => {
  const index = FACTOR_KEYS.indexOf(key as (typeof FACTOR_KEYS)[number]);
  return index >= 0 ? (session.mix[index] ?? 0) : 1;
};
/** The factor scored at least this share of its weight (and the weight is not zero). */
const strong = (row: Recommendation, key: string, session: Session, share: number) => {
  const weight = weightOf(key, session);
  return weight > 0 && (row.factors[key] ?? 0) >= share * weight;
};

/**
 * Plain-language reasons, derived from the factors that actually produced the score
 * (not from editorial labels), so the chips never claim something the ranking did not use.
 */
export function reasons(row: Recommendation, session: Session): string[] {
  const { content, evidence, because, popular } = row;
  const list: string[] = [];
  if (because.length) list.push(`Fans of ${because[0]} also like this`);
  if (popular) list.push('Crowd favourite');
  if (session.mood !== 'any' && strong(row, 'mood', session, 0.95)) list.push(`${capitalize(session.mood)} mood`);
  if (strong(row, 'intensity', session, 0.9)) {
    list.push(content.intensity < 0.35 ? 'Easygoing' : content.intensity > 0.65 ? 'Full throttle' : 'Right intensity');
  }
  if (evidence.length) list.push(`Your taste: ${evidence.slice(0, 2).join(' · ')}`);
  list.push(`${runtime(content.minutes)} · fits ${runtime(session.minutes)}`);
  return list;
}

/**
 * The same factors as one plain-English explanation, built from templates: instant, and it can only say
 * what the ranking actually used. (An optional local language model can reword it; see DetailsSheet.)
 */
export function explanation(row: Recommendation, session: Session): string {
  const { content, evidence, because, popular } = row;
  const kind = content.kind === 'episode' ? 'episode' : 'film';
  let lead: string;
  if (because.length) {
    lead = `People who liked ${because.slice(0, 2).join(' and ')} also rated this ${kind} highly`;
  } else if (popular) {
    lead = `It’s a crowd favourite while Flicks learns what you like`;
  } else if (evidence.length) {
    lead = `It shares ${evidence.slice(0, 2).join(' and ')} with what you liked`;
  } else {
    lead = `It fits the scene you set`;
  }
  const fits: string[] = [];
  if (session.mood !== 'any' && strong(row, 'mood', session, 0.95)) fits.push(`suits a ${session.mood} mood`);
  if (strong(row, 'intensity', session, 0.9)) {
    fits.push(
      content.intensity < 0.35
        ? 'keeps things easygoing'
        : content.intensity > 0.65
          ? 'brings the energy'
          : 'has the intensity you asked for',
    );
  }
  const scene = fits.length ? `, and it ${fits.join(' and ')}` : '';
  return `${lead}${scene}. At ${runtime(content.minutes)}, it fits the ${runtime(session.minutes)} you have.`;
}
