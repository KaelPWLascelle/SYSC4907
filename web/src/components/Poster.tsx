import { type CSSProperties, useState } from 'react';

import { posterUrl } from '../api/flicks';
import { hue } from '../lib/format';

interface PosterProps {
  item: { id: string; title: string; year: number };
  /** A cached poster exists for this title (from /api/state or the couch view). */
  hasPoster: boolean;
  className?: string;
  eager?: boolean;
}

/** The cached poster, or a generated title card when there is none or it fails to load. */
export function Poster({ item, hasPoster, className = 'poster', eager = false }: PosterProps) {
  // Remember which title failed, so a reused component showing another title tries again.
  const [failedId, setFailedId] = useState<string | null>(null);
  return (
    <div className={className}>
      {hasPoster && failedId !== item.id ? (
        <img
          src={posterUrl(item.id)}
          alt=""
          decoding="async"
          loading={eager ? 'eager' : 'lazy'}
          onError={() => setFailedId(item.id)}
        />
      ) : (
        <div className="poster-fallback" style={{ '--hue': hue(item.id) } as CSSProperties}>
          <span className="poster-fallback-title">{item.title}</span>
          <span className="poster-fallback-year">{item.year}</span>
        </div>
      )}
    </div>
  );
}
