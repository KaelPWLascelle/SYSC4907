import { spokenTime } from '../lib/format';

/** "Your usual night": the evening Flicks plans for when you don't say otherwise. */
export interface Night {
  /** 0 gentle .. 1 tense: the scene's intensity. */
  intensity: number;
  minutes: number;
}

export const NIGHT_MINUTES = { min: 60, max: 240, step: 15 } as const;

/** The usual night is a per-browser convenience, remembered per profile (like the mix); storage may be unavailable. */
const nightKey = (profile: number | undefined) => `flicks.night.${profile ?? 0}`;

export function savedNight(profile: number | undefined): Night | null {
  try {
    const value = JSON.parse(localStorage.getItem(nightKey(profile)) ?? 'null') as Partial<Night> | null;
    const { intensity, minutes } = value ?? {};
    const valid =
      typeof intensity === 'number' &&
      intensity >= 0 &&
      intensity <= 1 &&
      typeof minutes === 'number' &&
      Number.isInteger(minutes) &&
      minutes >= 1 &&
      minutes <= 600;
    return valid ? { intensity, minutes } : null;
  } catch {
    return null;
  }
}

export function saveNight(profile: number | undefined, night: Night) {
  try {
    localStorage.setItem(nightKey(profile), JSON.stringify(night));
  } catch {
    // Storage is unavailable (private window): the usual night lasts for this visit.
  }
}

export const nightWord = (intensity: number) =>
  intensity < 0.25
    ? 'gentle'
    : intensity < 0.45
      ? 'easy-going'
      : intensity <= 0.6
        ? 'balanced'
        : intensity < 0.8
          ? 'gripping'
          : 'tense';

/** "Most nights you want something easy-going, about 2 hours." */
export const describeNight = ({ intensity, minutes }: Night) =>
  `Most nights you want something ${nightWord(intensity)}, about ${spokenTime(minutes)}.`;
