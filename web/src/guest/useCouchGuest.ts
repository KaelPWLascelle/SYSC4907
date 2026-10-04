import { useCallback, useRef, useState } from 'react';

import type { CouchGuestView, PlayerAction, Rating } from '../api/types';
import { useVisiblePolling } from '../lib/useVisiblePolling';
import { guestApi, isSessionGone, tokenStore } from './api';

const LOST = 'Can’t reach the TV. The couch session may have ended, or this phone left the Wi-Fi.';

/**
 * A guest's view of the session. `epoch` drops any poll that started before this phone's own
 * latest action, so a slow reply can never undo a vote or a remote press.
 */
export function useCouchGuest() {
  const [token, setToken] = useState(tokenStore.get);
  const [view, setView] = useState<CouchGuestView | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const epoch = useRef(0);
  const busyRef = useRef(false);

  const leave = useCallback(() => {
    tokenStore.set(null);
    setToken(null);
    setView(null);
  }, []);

  const refresh = useCallback(async () => {
    if (!token || busyRef.current) return;
    const started = epoch.current;
    try {
      const next = await guestApi.state(token);
      if (started !== epoch.current || busyRef.current) return;
      setView(previous => (previous?.version === next.version ? previous : next));
      setMessage('');
    } catch (error) {
      if (isSessionGone(error)) leave();
      else setMessage(LOST);
    }
  }, [token, leave]);
  useVisiblePolling(refresh, token !== null);

  const act = useCallback(
    async (action: (token: string) => Promise<CouchGuestView>) => {
      if (!token || busyRef.current) return;
      busyRef.current = true;
      epoch.current++;
      setBusy(true);
      try {
        setView(await action(token));
        setMessage('');
      } catch (error) {
        if (isSessionGone(error)) leave();
        else setMessage(error instanceof Error ? error.message : String(error));
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [token, leave],
  );

  const join = useCallback(async (code: string, name: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const joined = await guestApi.join(code.trim().toUpperCase(), name);
      tokenStore.set(joined.token);
      setView(await guestApi.state(joined.token));
      setToken(joined.token);
      setMessage(`You’re in, ${joined.name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, []);

  return {
    joined: token !== null && view !== null,
    view,
    message,
    busy,
    join,
    vote: (id: string, value: Rating | 0) => act(t => guestApi.vote(t, id, value)),
    remote: (action: PlayerAction, id?: string) => act(t => guestApi.remote(t, action, id)),
  };
}
