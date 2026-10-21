import type { Content, SeriesInfo } from '../api/types';

export const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** "2016 · 1h 56m" for a film; "2008–2013 · 5 seasons" for a series. */
export function subtitle(item: Pick<Content, 'year' | 'minutes' | 'series'>): string {
  const { series } = item;
  if (!series) return `${item.year} · ${runtime(item.minutes)}`;
  return `${aired(item.year, series)} · ${plural(series.seasons, 'season')}`;
}

/** "2008–2013", "2019–" while it runs, or "2016" for one year. */
export function aired(year: number, series: SeriesInfo): string {
  return series.ended === year ? String(year) : `${year}–${series.ended ?? ''}`;
}

/** "62 episodes of about 1h · AMC". */
export function episodes(item: Pick<Content, 'minutes'> & { series: SeriesInfo }): string {
  const { series } = item;
  const length = `${plural(series.episodes, 'episode')} of about ${runtime(item.minutes)}`;
  return series.network ? `${length} · ${series.network}` : length;
}

export const plural = (count: number, word: string) => `${count.toLocaleString('en')} ${word}${count === 1 ? '' : 's'}`;

/** 52_428_800 -> "50 MB". */
export const megabytes = (bytes: number) => `${Math.round(bytes / 1_048_576)} MB`;

/** 116 -> "1h 56m", 45 -> "45m", 120 -> "2h". */
export function runtime(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const rest = minutes % 60;
  return `${Math.floor(minutes / 60)}h${rest ? ` ${rest}m` : ''}`;
}

/** Seconds -> "1:02:03" or "4:05" for player timestamps. */
export function timestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}

/** A stable hue per title, for generated title cards. FNV-1a, so similar IDs ("ml1", "ml2") differ. */
export function hue(id: string): number {
  let h = 0x811c9dc5;
  for (const c of id) h = Math.imul(h ^ c.charCodeAt(0), 0x01000193) >>> 0;
  return h % 360;
}

/** "2 hours", "1½ hours", "45 minutes": how a person says a time budget. */
export function spokenTime(minutes: number) {
  if (minutes < 60) return `${minutes} minutes`;
  if (minutes % 60 === 0) return minutes === 60 ? '1 hour' : `${minutes / 60} hours`;
  if (minutes % 60 === 30) return `${Math.floor(minutes / 60)}½ hours`;
  return runtime(minutes);
}
