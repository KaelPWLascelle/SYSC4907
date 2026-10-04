/**
 * Route-based fetch stub for component tests: `'GET /api/state'` -> handler returning [status, body].
 * Handlers may return a promise to hold a reply back (for race-condition tests). Records every call.
 */
import { vi } from 'vitest';

export type Reply = [number, unknown] | Promise<[number, unknown]>;
export type Handler = (body: unknown, init: RequestInit) => Reply;

export interface Call {
  method: string;
  path: string;
  body: unknown;
  headers: Record<string, string>;
}

export function mockFetch(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://127.0.0.1');
    const method = (init.method ?? 'GET').toUpperCase();
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    calls.push({ method, path: url.pathname, body, headers: { ...(init.headers as Record<string, string>) } });
    const handler = routes[`${method} ${url.pathname}`];
    if (!handler) return jsonResponse(404, { error: `No mock for ${method} ${url.pathname}` });
    const [status, data] = await handler(body, init);
    return jsonResponse(status, data);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}

function jsonResponse(status: number, data: unknown) {
  return new Response(status === 204 ? null : JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** A promise you resolve later, for holding a reply back. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => (resolve = r));
  return { promise, resolve };
}
