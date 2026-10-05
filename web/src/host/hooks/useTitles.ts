import { useCallback, useEffect, useMemo, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import type { Content, Rating, TitleFilter } from '../../api/types';
import { useDebounced } from '../../lib/useDebounced';

export const PAGE_SIZE = 48;

interface Pages {
  key: string;
  items: Content[];
  total: number;
  error: string | null;
}

/**
 * Server-side catalogue search, one page at a time. Typing is debounced and a newer search aborts the
 * older one. Rating filters refetch when ratings change; "all" does not need to.
 */
export function useTitles(query: string, show: TitleFilter, feedback: Record<string, Rating>) {
  const q = useDebounced(query.trim(), 200);
  const key = useMemo(() => JSON.stringify([q, show, show === 'all' ? null : feedback]), [q, show, feedback]);
  const [pages, setPages] = useState<Pages | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    flicksApi.titles({ q, show, offset: 0, limit: PAGE_SIZE }, { signal: controller.signal }).then(
      page => setPages({ key, items: page.items, total: page.total, error: null }),
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setPages({ key, items: [], total: 0, error: error instanceof Error ? error.message : String(error) });
        }
      },
    );
    return () => controller.abort();
  }, [key, q, show]);

  const current = pages?.key === key ? pages : null;
  const loadMore = useCallback(async () => {
    if (!current || current.items.length >= current.total) return;
    setLoadingMore(true);
    try {
      const page = await flicksApi.titles({ q, show, offset: current.items.length, limit: PAGE_SIZE });
      setPages(previous =>
        previous?.key === key ? { ...previous, items: [...previous.items, ...page.items] } : previous,
      );
    } catch (error) {
      setPages(previous =>
        previous ? { ...previous, error: error instanceof Error ? error.message : String(error) } : previous,
      );
    } finally {
      setLoadingMore(false);
    }
  }, [current, key, q, show]);

  return {
    items: current?.items ?? pages?.items ?? [],
    total: current?.total ?? 0,
    loading: current === null,
    loadingMore,
    error: current?.error ?? null,
    loadMore,
  };
}
