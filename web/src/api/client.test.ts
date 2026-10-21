import { vi } from 'vitest';

import { actAs, PROFILE_CHANGED, request } from './client';

afterEach(() => actAs(null));

test('a reply saying the profile changed is announced to the page', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ error: 'The profile on this page is no longer signed in.' }), {
          status: 409,
          headers: { 'Content-Type': 'application/json', 'X-Flicks-Profile-Changed': '1' },
        }),
    ),
  );
  const heard = vi.fn();
  window.addEventListener(PROFILE_CHANGED, heard);
  actAs(2);
  await expect(request('/api/feedback', { method: 'POST' })).rejects.toThrow('no longer signed in');
  expect(heard).toHaveBeenCalledOnce();
  expect(vi.mocked(fetch).mock.calls.at(0)?.[1]?.headers).toEqual({ 'X-Flicks-Profile': '2' });
  window.removeEventListener(PROFILE_CHANGED, heard);
});
