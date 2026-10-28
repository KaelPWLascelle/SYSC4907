import { useCallback, useEffect, useState } from 'react';

/** What fades when the lights go down: everything but tonight's poster under its spotlight. */
const FADES = '.topbar, .hero-copy, main > :not(.hero), .footer';

/**
 * The house lights. Down, the page fades to near-black except the spotlit poster, and the pointer carries
 * a faint torch so you can still find your way. The bulb on the i, or L, switches them; Escape brings them up.
 */
export function useHouseLights() {
  const [dim, setDim] = useState(false);
  const toggle = useCallback(() => setDim(down => !down), []);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle('is-dim', dim);
    if (!dim) return;
    let frame = 0;
    const torch = (event: PointerEvent) => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        // Each faded block learns where the pointer is relative to itself (masks are local to an element).
        for (const node of document.querySelectorAll<HTMLElement>(FADES)) {
          const box = node.getBoundingClientRect();
          node.style.setProperty('--tx', `${event.clientX - box.left}px`);
          node.style.setProperty('--ty', `${event.clientY - box.top}px`);
        }
      });
    };
    window.addEventListener('pointermove', torch);
    return () => {
      window.removeEventListener('pointermove', torch);
      cancelAnimationFrame(frame);
      root.classList.remove('is-dim');
    };
  }, [dim]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (target.closest('input, textarea, select, [contenteditable], dialog')) return;
      if (event.key === 'l' || event.key === 'L') setDim(down => !down);
      else if (event.key === 'Escape') setDim(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  return { dim, toggle };
}
