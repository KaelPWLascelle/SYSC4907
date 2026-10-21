import { useId } from 'react';

/**
 * The Flicks mark: five bars that together point right like a play button, and read as a sound wave on
 * its side. The bars echo the factor bars behind every pick (you can always see why), and the wave nods
 * to the sound of a film starting. White on Flicks blue, in a self-contained tile
 * (everything stays on this device). The same geometry is in web/public/favicon.svg and
 * scripts/make_icons.py.
 */
const BARS = [
  { y: 8.4, width: 3 },
  { y: 11.6, width: 8.4 },
  { y: 14.8, width: 14 },
  { y: 18, width: 8.4 },
  { y: 21.2, width: 3 },
] as const;

export function Logo() {
  const id = useId();
  return (
    <>
      <svg className="logo-mark" viewBox="0 0 32 32" aria-hidden="true">
        <defs>
          <linearGradient id={`${id}-tile`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#2f80ff" />
            <stop offset="1" stopColor="#7a5cff" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="9" fill={`url(#${id}-tile)`} />
        {BARS.map(bar => (
          <rect key={bar.y} x="11" y={bar.y} width={bar.width} height="2.4" rx="1.2" fill="#fff" />
        ))}
      </svg>
      <span className="logo-word">flicks</span>
    </>
  );
}
