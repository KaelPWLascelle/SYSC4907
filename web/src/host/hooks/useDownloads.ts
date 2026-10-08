import { useCallback, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import type { DownloadStatus } from '../../api/types';
import { useVisiblePolling } from '../../lib/useVisiblePolling';

const active = (status: DownloadStatus) => status.state === 'queued' || status.state === 'downloading';

/**
 * Podcast downloads by episode ID (absent means not downloaded). Polls only while one is queued or in
 * progress, so an idle page makes no requests.
 */
export function useDownloads(enabled: boolean) {
  const [downloads, setDownloads] = useState<ReadonlyMap<string, DownloadStatus>>(new Map());
  const [error, setError] = useState('');
  const [watching, setWatching] = useState(enabled);

  const refresh = useCallback(async () => {
    try {
      const next = new Map(Object.entries((await flicksApi.podcasts.downloads()).downloads));
      setDownloads(next);
      setWatching([...next.values()].some(active));
    } catch {
      // A missed poll is retried on the next tick; downloads keep running on the server regardless.
    }
  }, []);
  useVisiblePolling(refresh, enabled && watching);

  const download = useCallback(async (id: string) => {
    try {
      const status = await flicksApi.podcasts.download(id);
      setDownloads(previous => new Map(previous).set(id, status));
      setWatching(true);
      setError('');
    } catch (failure) {
      setError(`Could not start the download: ${failure instanceof Error ? failure.message : String(failure)}`);
    }
  }, []);

  const remove = useCallback(async (id: string) => {
    try {
      await flicksApi.podcasts.remove(id);
      setDownloads(previous => {
        const next = new Map(previous);
        next.delete(id);
        return next;
      });
      setError('');
    } catch (failure) {
      setError(`Could not remove the download: ${failure instanceof Error ? failure.message : String(failure)}`);
    }
  }, []);

  return { downloads, download, remove, error };
}
