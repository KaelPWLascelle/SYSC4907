/** The host app's API (loopback). Couch guests use src/guest/api.ts instead. */
import { json, request, streamLines } from './client';
import type {
  AppState,
  AskTitleEvent,
  AskTurn,
  CommandResponse,
  CouchHostView,
  DiscoverResponse,
  ExplainResponse,
  ImportResult,
  Mode,
  PickPool,
  PickResponse,
  PlayerAction,
  ProfilesResponse,
  ProfileSummary,
  Progress,
  Rating,
  RecommendResponse,
  Session,
  TitleFilter,
  TasteResponse,
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
  taste: (signal?: AbortSignal) => request<TasteResponse>('/api/taste', { signal }),
  explain: (id: string, session: Session, signal?: AbortSignal) =>
    request<ExplainResponse>('/api/explain', { ...json('POST', { id, session }), signal }),
  /** A question about one title, answered word by word by the local language model (assistant/title_chat.py). */
  askTitle: (
    query: { id: string; question: string; session: Session; history: AskTurn[] },
    onEvent: (event: AskTitleEvent) => void,
    signal?: AbortSignal,
  ) => streamLines<AskTitleEvent>('/api/ask-title', { ...json('POST', query), signal }, onEvent),
  discover: (query: { session: Session; seen: string[]; online: boolean; limit?: number }, signal?: AbortSignal) =>
    request<DiscoverResponse>('/api/discover', { ...json('POST', query), signal }),
  pick: (session: Session, pool: PickPool) => request<PickResponse>('/api/pick', json('POST', { session, pool })),
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

  profiles: {
    list: () => request<ProfilesResponse>('/api/profiles'),
    create: (name: string, pin: string | null) =>
      request<{ profile: ProfileSummary }>('/api/profiles', json('POST', { name, pin })),
    select: (id: number, pin: string | null) =>
      request<{ profile: ProfileSummary }>(`/api/profiles/${id}/select`, json('POST', { pin })),
    signOut: () => request<{ ok: boolean }>('/api/profiles/signout', json('POST', {})),
    update: (change: { name?: string; pin?: string | null; current_pin?: string | null }) =>
      request<{ profile: ProfileSummary }>('/api/profiles/current', json('PUT', change)),
    remove: () => request<ProfilesResponse>('/api/profiles/current', { method: 'DELETE' }),
    clearData: () => request<undefined>('/api/profiles/current/data', { method: 'DELETE' }),
    import: (file: Blob, mode: 'new' | 'merge') =>
      request<ImportResult>(`/api/profiles/import?mode=${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: file,
      }),
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

/** A download link: the browser saves the profile's ratings and history as a JSON file. */
export const EXPORT_URL = '/api/profiles/current/export';
export const mediaUrl = (id: string) => `/media/${encodeURIComponent(id)}`;
export const posterUrl = (id: string) => `/posters/${encodeURIComponent(id)}`;
