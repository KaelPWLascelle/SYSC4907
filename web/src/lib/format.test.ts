import { SERIES, SERIES_INFO } from '../test/fixtures';
import { episodes, hue, runtime, subtitle, timestamp } from './format';

test('a film shows its length; a series its years and seasons', () => {
  expect(subtitle({ year: 2016, minutes: 116 })).toBe('2016 · 1h 56m');
  expect(subtitle(SERIES)).toBe('2008–2013 · 5 seasons');
  const running = { ...SERIES_INFO, ended: null, seasons: 1 };
  expect(subtitle({ ...SERIES, series: running })).toBe('2008– · 1 season');
  expect(episodes({ ...SERIES, series: SERIES_INFO })).toBe('62 episodes of about 1h · AMC');
});

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
