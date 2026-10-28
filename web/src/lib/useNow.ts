import { useEffect, useState } from 'react';

/** The current time, refreshed every minute: for "ends around 9:42 pm" that stays true while you browse. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

/** "9:42 pm": the clock time `minutes` after `now`. */
export const clockAfter = (now: number, minutes: number) =>
  new Date(now + minutes * 60_000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();
