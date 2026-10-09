/** The host app's API (loopback). Couch guests use src/guest/api.ts instead. */
import { json, request } from './client';
import type {
  AppState,
  CommandResponse,
  CouchHostView,
  DownloadStatus,
  Mode,
  PlayerAction,
  Progress,
  Rating,
  RecommendResponse,
  Session,
  TitleFilter,
  TitlesResponse,
  TranscribeResponse,
} from './types';

export const flicksApi = {
  state: () => request<AppState>('/api/state'),
  recommend: (session: Session, mode: Mode, init?: RequestInit) =>
    request<RecommendResponse>('/api/recommend', { ...json('POST', { session, mode }), ...init }),
  titles: (
    query: { q: string; show: TitleFilter; similar?: string | null; offset: number; limit: number },
    init?: RequestInit,
  ) => {
    const params = new URLSearchParams({
      q: query.q,
      show: query.show,
      offset: String(query.offset),
      limit: String(query.limit),
    });
    if (query.similar) params.set('similar', query.similar);
    return request<TitlesResponse>(`/api/titles?${params}`, init);
  },
  rate: (id: string, value: Rating | 0) =>
    request<{ feedback: Record<string, Rating> }>('/api/feedback', json('POST', { id, value })),

  previewCommand: (text: string, session: Session) =>
    request<CommandResponse>('/api/command/preview', json('POST', { text, session })),
  applyCommand: (text: string, session: Session) =>
    request<CommandResponse>('/api/command/apply', json('POST', { text, session })),
  transcribe: (audio: Blob, signal: AbortSignal) =>
    request<TranscribeResponse>('/api/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': audio.type || 'application/octet-stream' },
      body: audio,
      signal,
    }),

  history: () => request<{ items: Progress[] }>('/api/history'),
  saveProgress: (id: string, position_seconds: number, duration_seconds: number) =>
    request<Progress>(`/api/history/${encodeURIComponent(id)}`, json('PUT', { position_seconds, duration_seconds })),
  clearProgress: (id: string) => request<undefined>(`/api/history/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  podcasts: {
    downloads: () => request<{ downloads: Record<string, DownloadStatus> }>('/api/podcasts/downloads'),
    download: (id: string) =>
      request<DownloadStatus>(`/api/podcasts/${encodeURIComponent(id)}/download`, json('POST', {})),
    remove: (id: string) =>
      request<undefined>(`/api/podcasts/${encodeURIComponent(id)}/download`, { method: 'DELETE' }),
  },

  couch: {
    view: () => request<CouchHostView>('/api/couch'),
    start: (session: Session) => request<CouchHostView>('/api/couch/start', json('POST', { session })),
    stop: () => request<CouchHostView>('/api/couch/stop', json('POST', {})),
    reveal: () => request<CouchHostView>('/api/couch/reveal', json('POST', {})),
    player: (action: PlayerAction, id?: string) =>
      request<CouchHostView>('/api/couch/player', json('POST', id ? { action, id } : { action })),
  },
};

export const mediaUrl = (id: string) => `/media/${encodeURIComponent(id)}`;
export const posterUrl = (id: string) => `/posters/${encodeURIComponent(id)}`;
