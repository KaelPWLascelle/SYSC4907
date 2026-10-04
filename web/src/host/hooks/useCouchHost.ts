import { useCallback, useRef, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import type { CouchHostView, PlayerAction, Session } from '../../api/types';
import { useVisiblePolling } from '../../lib/useVisiblePolling';

/**
 * The TV side of couch mode. Polls the loopback API; `epoch` drops any poll that started before
 * the host's own latest action, so a stale reply can never overwrite a newer state.
 */
export function useCouchHost(enabled: boolean) {
  const [view, setView] = useState<CouchHostView>({ active: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const epoch = useRef(0);
  const busyRef = useRef(false);

  const refresh = useCallback(async () => {
    if (busyRef.current) return;
    const started = epoch.current;
    try {
      const next = await flicksApi.couch.view();
      if (started !== epoch.current || busyRef.current) return;
      setView(previous => (sameView(previous, next) ? previous : next));
    } catch (failure) {
      setError(`Couch mode: ${failure instanceof Error ? failure.message : String(failure)}`);
    }
  }, []);
  useVisiblePolling(refresh, enabled);

  const run = useCallback(async (action: () => Promise<CouchHostView>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    epoch.current++;
    setBusy(true);
    try {
      setView(await action());
      setError('');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, []);

  return {
    view,
    busy,
    error,
    start: (session: Session) => run(() => flicksApi.couch.start(session)),
    stop: () => run(flicksApi.couch.stop),
    reveal: () => run(flicksApi.couch.reveal),
    player: (action: PlayerAction, id?: string) => run(() => flicksApi.couch.player(action, id)),
  };
}

function sameView(a: CouchHostView, b: CouchHostView) {
  if (!a.active || !b.active) return a.active === b.active;
  return a.version === b.version && a.code === b.code;
}
