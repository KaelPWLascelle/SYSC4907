import { normalizeMix, sameMix } from './mix';

test('a mix always sums to 1, with no negative weight, and a zero slider stays zero', () => {
  for (const values of [
    [55, 20, 15, 10],
    [0, 1, 1, 1],
    [0, 5, 5, 5],
    [100, 0, 0, 0],
    [0, 0, 0, 7],
    [33, 33, 33, 1],
    [50, 30, 30, 0],
  ]) {
    const mix = normalizeMix(values);
    expect(Math.round(mix.reduce((a, b) => a + b, 0) * 1000)).toBe(1000);
    expect(mix.every(w => w >= 0)).toBe(true);
    values.forEach((v, i) => v === 0 && expect(mix[i]).toBe(0));
  }
  expect(normalizeMix([0, 0, 0, 0])).toEqual([0.55, 0.2, 0.15, 0.1]);
  expect(normalizeMix([50, 50, 0, 0])).toEqual([0.5, 0.5, 0, 0]);
});

test('a saved mix read back into the sliders is unchanged (no phantom edits)', () => {
  const saved = normalizeMix([50, 30, 30, 0]);
  expect(saved).toEqual([0.454, 0.273, 0.273, 0]); // 454.5, 272.7, 272.7 thousandths by largest remainder
  expect(sameMix(normalizeMix(saved.map(w => w * 100)), saved)).toBe(true);
});
