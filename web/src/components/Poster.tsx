import { type CSSProperties, useState } from 'react';

import { posterUrl } from '../api/flicks';
import { hue } from '../lib/format';

interface PosterProps {
  /** A podcast episode's card names its show where a film's names its year, and shows square art whole. */
  item: { id: string; title: string; year?: number; kind?: string; series?: string | null };
  /** A cached poster exists for this title (from /api/state or the couch view). */
  hasPoster: boolean;
  className?: string;
  eager?: boolean;
}

/** The cached poster, or a generated title card when there is none or it fails to load. */
export function Poster({ item, hasPoster, className = 'poster', eager = false }: PosterProps) {
  // Remember which title failed, so a reused component showing another title tries again.
  const [failedId, setFailedId] = useState<string | null>(null);
  const loading = eager ? 'eager' : 'lazy';
  const episode = item.kind === 'episode';
  return (
    <div className={className}>
      {hasPoster && failedId !== item.id ? (
        episode ? (
          <>
            <img className="poster-blur" src={posterUrl(item.id)} alt="" decoding="async" loading={loading} />
            <img
              className="poster-square"
              src={posterUrl(item.id)}
              alt=""
              decoding="async"
              loading={loading}
              onError={() => setFailedId(item.id)}
            />
            <span className="poster-caption">{item.title}</span>
          </>
        ) : (
          <img
            src={posterUrl(item.id)}
            alt=""
            decoding="async"
            loading={loading}
            onError={() => setFailedId(item.id)}
          />
        )
      ) : (
        <div className="poster-fallback" style={{ '--hue': hue(item.id) } as CSSProperties}>
          <span className="poster-fallback-title">{item.title}</span>
          {(item.series ?? item.year) !== undefined && (
            <span className="poster-fallback-year">{item.series ?? item.year}</span>
          )}
        </div>
      )}
    </div>
  );
}
