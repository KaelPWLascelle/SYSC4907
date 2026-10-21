/** Minimal JSON client. Every error response from Flicks has the shape {"error": "..."}. */

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** The profile this page was loaded for; sent with every request so the server never saves to another. */
let actingFor: number | null = null;
export function actAs(profileId: number | null) {
  actingFor = profileId;
}
/** Dispatched on window when the server says this page's profile is no longer signed in. */
export const PROFILE_CHANGED = 'flicks:profile-changed';

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = actingFor === null ? init.headers : { ...init.headers, 'X-Flicks-Profile': String(actingFor) };
  const response = await fetch(path, headers ? { ...init, headers } : init);
  if (response.headers.get('X-Flicks-Profile-Changed')) window.dispatchEvent(new Event(PROFILE_CHANGED));
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
