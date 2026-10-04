import { useEffect, useMemo, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import type { Mode, Rating, Recommendation, Session } from '../../api/types';
import { useDebounced } from '../../lib/useDebounced';

export interface Recommendations {
  picks: Recommendation[];
  coldStart: boolean;
  /** A request for the current scene and ratings is in flight; `picks` still shows the previous result. */
  loading: boolean;
  error: string | null;
}

interface Result {
  key: string;
  picks: Recommendation[];
  coldStart: boolean;
  error: string | null;
}

/**
 * Picks for the current scene. Scene changes are debounced (sliders fire continuously); rating changes
 * refetch at once. A newer request aborts the older one, so results never arrive out of order.
 */
export function useRecommendations(session: Session, mode: Mode, feedback: Record<string, Rating>): Recommendations {
  const query = useDebounced(
    useMemo(() => JSON.stringify({ session, mode }), [session, mode]),
    160,
  );
  const key = useMemo(() => `${query}|${JSON.stringify(feedback)}`, [query, feedback]);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { session: s, mode: m } = JSON.parse(query) as { session: Session; mode: Mode };
    flicksApi.recommend(s, m, { signal: controller.signal }).then(
      response => setResult({ key, picks: response.recommendations, coldStart: response.cold_start, error: null }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : String(error);
        setResult(previous => ({
          key,
          picks: previous?.picks ?? [],
          coldStart: previous?.coldStart ?? true,
          error: message,
        }));
      },
    );
    return () => controller.abort();
  }, [key, query]);

  return {
    picks: result?.picks ?? [],
    coldStart: result?.coldStart ?? true,
    loading: result?.key !== key,
    error: result?.key === key ? result.error : null,
  };
}
