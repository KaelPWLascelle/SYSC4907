import { DEFAULT_MIX, type Mix } from '../api/types';

/**
 * Turn four slider values (any scale) into a mix that sums to exactly 1, in thousandths, by largest
 * remainder: each weight is its exact share rounded down, and the leftover thousandths go to the largest
 * fractions. A slider at 0 always stays 0; all zero falls back to the default.
 */
export function normalizeMix(values: number[]): Mix {
  const clean = values.slice(0, 4).map(v => (Number.isFinite(v) && v > 0 ? v : 0));
  const total = clean.reduce((sum, v) => sum + v, 0);
  if (total <= 0) return DEFAULT_MIX;
  const exact = clean.map(v => (v / total) * 1000);
  const floors = exact.map(v => Math.floor(v + 1e-9));
  let left = 1000 - floors.reduce((sum, v) => sum + v, 0);
  const byFraction = exact.map((v, i) => [v - (floors[i] ?? 0), i] as const).sort((a, b) => b[0] - a[0]);
  for (const [fraction, i] of byFraction) {
    if (left <= 0) break;
    if (fraction > 1e-9) {
      floors[i] = (floors[i] ?? 0) + 1;
      left--;
    }
  }
  return floors.map(v => v / 1000) as Mix;
}

/** Two mixes are the same when every weight matches to the thousandth. */
export const sameMix = (a: readonly number[], b: readonly number[]) =>
  a.length === b.length && a.every((w, i) => Math.abs(w - (b[i] ?? 0)) < 0.0005);
