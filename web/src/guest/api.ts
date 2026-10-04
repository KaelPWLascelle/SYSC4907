/** The couch guest server's API (home network). The guest token travels in a header, never the URL. */
import { ApiError, json, request } from '../api/client';
import type { CouchGuestView, PlayerAction, Rating } from '../api/types';

const STORAGE_KEY = 'flicks-guest';

/** sessionStorage can throw (private mode, blocked storage); the token then lasts for this page only. */
export const tokenStore = {
  get(): string | null {
    try {
      return sessionStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  },
  set(token: string | null) {
    try {
      if (token) sessionStorage.setItem(STORAGE_KEY, token);
      else sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // Not persisted; acceptable.
    }
  },
};

const auth = (token: string) => ({ 'X-Flicks-Guest': token });

export const guestApi = {
  join: (code: string, name: string) =>
    request<{ token: string; name: string }>('/api/couch/join', json('POST', { code, name })),
  state: (token: string) => request<CouchGuestView>('/api/couch/state', { headers: auth(token) }),
  vote: (token: string, id: string, value: Rating | 0) =>
    request<CouchGuestView>('/api/couch/vote', json('POST', { id, value }, auth(token))),
  remote: (token: string, action: PlayerAction, id?: string) =>
    request<CouchGuestView>('/api/couch/remote', json('POST', id ? { action, id } : { action }, auth(token))),
};

/** 401: unknown or expired token. 410: the session ended. Either way, start over at the join screen. */
export const isSessionGone = (error: unknown) =>
  error instanceof ApiError && (error.status === 401 || error.status === 410);
