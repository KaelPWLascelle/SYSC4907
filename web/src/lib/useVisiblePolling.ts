import { useEffect, useRef } from 'react';

/**
 * Calls `poll` now, then every `intervalMs` while the page is visible, and again as soon as a hidden
 * page becomes visible (a locked phone, a background tab). The latest `poll` is always used.
 */
export function useVisiblePolling(poll: () => void | Promise<void>, enabled: boolean, intervalMs = 1500) {
  const latest = useRef(poll);
  useEffect(() => {
    latest.current = poll;
  });

  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const tick = async () => {
      if (!document.hidden) await latest.current();
      if (!stopped) timer = setTimeout(tick, intervalMs);
    };
    const onVisible = () => {
      if (!document.hidden) void latest.current();
    };
    void latest.current(); // load immediately, even in a background tab
    timer = setTimeout(tick, intervalMs);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [enabled, intervalMs]);
}
