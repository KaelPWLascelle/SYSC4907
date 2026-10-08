export const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** "2016 · 1h 56m" for a film, "In Our Time · 50m" for a podcast episode. */
export function subtitle(item: { kind: string; year: number; minutes: number; series?: string | null }): string {
  return `${item.kind === 'episode' ? (item.series ?? 'Podcast') : item.year} · ${runtime(item.minutes)}`;
}

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

/** A stable hue per title, for generated title cards. */
export function hue(id: string): number {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}
