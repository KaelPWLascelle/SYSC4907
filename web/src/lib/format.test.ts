import { hue, runtime, timestamp } from './format';

test('runtime', () => {
  expect([runtime(45), runtime(60), runtime(116), runtime(120)]).toEqual(['45m', '1h', '1h 56m', '2h']);
});

test('timestamp', () => {
  expect([timestamp(0), timestamp(65.9), timestamp(3723), timestamp(-4)]).toEqual(['0:00', '1:05', '1:02:03', '0:00']);
});

test('hue is stable and in range', () => {
  expect(hue('m001')).toBe(hue('m001'));
  expect(hue('m001')).toBeGreaterThanOrEqual(0);
  expect(hue('m001')).toBeLessThan(360);
});
