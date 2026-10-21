import { useEffect, useRef } from 'react';

/**
 * Calls `poll` now, then every `intervalMs` while the page is visible, and again as soon as a hidden
 * page becomes visible (a locked phone, a background tab). The latest `poll` is always used.
 *
 * Changing `intervalMs` only reschedules the next poll; it does not poll at once, so a caller that just
 * set its own state (and sped polling up because of it) is not overwritten by an immediate fetch.
 */
export function useVisiblePolling(poll: () => void | Promise<void>, enabled: boolean, intervalMs = 1500) {
  const latest = useRef(poll);
  const interval = useRef(intervalMs);
  const reschedule = useRef<() => void>(() => undefined);
  useEffect(() => {
    latest.current = poll;
  });

  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    // Each chain of polls has a generation; rescheduling starts a new one, and a poll still in flight from
    // the old chain does not schedule another after it returns, so two chains never run side by side.
    let generation = 0;
    const tick = async (mine: number) => {
      if (!document.hidden) await latest.current();
      if (!stopped && mine === generation) timer = setTimeout(() => void tick(mine), interval.current);
    };
    const schedule = () => {
      clearTimeout(timer);
      const mine = ++generation;
      timer = setTimeout(() => void tick(mine), interval.current);
    };
    reschedule.current = () => {
      if (!stopped) schedule();
    };
    const onVisible = () => {
      if (!document.hidden) void latest.current();
    };
    void latest.current(); // load immediately, even in a background tab
    schedule();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      stopped = true;
      clearTimeout(timer);
      reschedule.current = () => undefined;
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [enabled]);

  useEffect(() => {
    if (interval.current === intervalMs) return;
    interval.current = intervalMs;
    reschedule.current();
  }, [intervalMs]);
}
