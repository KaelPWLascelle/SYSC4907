/** Minimal JSON client. Every error response from Flicks has the shape {"error": "..."}. */

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, init);
  if (response.status === 204) return undefined as T;
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    const message = (body as { error?: unknown } | undefined)?.error;
    throw new ApiError(typeof message === 'string' ? message : `Request failed (${response.status})`, response.status);
  }
  return body as T;
}

export function json(method: 'POST' | 'PUT', data: unknown, headers: Record<string, string> = {}): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(data) };
}
