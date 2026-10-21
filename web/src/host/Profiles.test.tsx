import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { AppState, CurrentProfile } from '../api/types';
import { ALPHA, CATALOG, appState, pick } from '../test/fixtures';
import { mockFetch } from '../test/fetchMock';
import { App } from './App';
import { PROFILE_CHANGED } from '../api/client';

const ME: CurrentProfile = { id: 1, name: 'Me', locked: false, chosen: false, count: 2 };
const PROFILES = [
  { id: 1, name: 'Me', locked: false, created_at: '2026-10-01T00:00:00.000Z', ratings: 3 },
  { id: 2, name: 'Sam', locked: true, created_at: '2026-10-02T00:00:00.000Z', ratings: 0 },
];

type Route = (body: unknown, init: RequestInit) => [number, unknown] | [number, unknown, Record<string, string>];

/** Like the real server: a request naming a profile other than the signed-in one is refused with 409. */
function enforced(state: () => AppState): Route {
  return (_body, init) => {
    const named = (init.headers as Record<string, string> | undefined)?.['X-Flicks-Profile'];
    const current = state().profile;
    if (named && current && named !== String(current.id)) {
      return [409, { error: 'The profile on this page is no longer signed in.' }, { 'X-Flicks-Profile-Changed': '1' }];
    }
    return [200, state()];
  };
}

function setup(state: () => AppState, extra: Record<string, Route> = {}) {
  return mockFetch({
    'GET /api/state': enforced(state),
    'GET /api/profiles': () => [200, { profiles: PROFILES, current: ME, chosen: false }],
    'GET /api/history': () => [200, { items: [] }],
    'GET /api/titles': () => [200, { items: CATALOG, total: CATALOG.length, understood: [] }],
    'POST /api/recommend': () => [200, { recommendations: [pick(ALPHA)], cold_start: false }],
    ...extra,
  });
}

test('with several profiles, Flicks asks who is watching and a PIN profile asks for its PIN', async () => {
  let chosen = false;
  const { calls } = setup(
    () => appState({ profile: { ...ME, chosen, name: chosen ? 'Sam' : 'Me', id: chosen ? 2 : 1 } }),
    {
      'POST /api/profiles/2/select': body => {
        if ((body as { pin: string | null }).pin !== '2468') return [403, { error: 'Wrong PIN' }];
        chosen = true;
        return [200, { profile: PROFILES[1] }];
      },
    },
  );
  render(<App />);
  expect(await screen.findByRole('heading', { name: 'Who’s watching?' })).toBeInTheDocument();
  await userEvent.click(await screen.findByRole('button', { name: /Sam/ }));
  await userEvent.type(screen.getByLabelText('PIN for Sam'), '1111');
  await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Wrong PIN');
  await userEvent.clear(screen.getByLabelText('PIN for Sam'));
  await userEvent.type(screen.getByLabelText('PIN for Sam'), '2468');
  await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
  expect(await screen.findByRole('button', { name: 'Profile: Sam' })).toBeInTheDocument();
  expect(calls.filter(c => c.path === '/api/profiles/2/select')).toHaveLength(2);
});

test('a single profile goes straight to the picks, and its menu exports and clears data', async () => {
  let cleared = false;
  const { calls } = setup(() => appState({ profile: { ...ME, count: 1 }, feedback: cleared ? {} : { m2: 1 } }), {
    'DELETE /api/profiles/current/data': () => {
      cleared = true;
      return [204, null];
    },
  });
  render(<App />);
  await userEvent.click(await screen.findByRole('button', { name: 'Profile: Me' }));
  const menu = screen.getByRole('dialog', { name: 'Me' });
  expect(within(menu).getByRole('link', { name: /Export ratings and history/ })).toHaveAttribute(
    'href',
    '/api/profiles/current/export',
  );
  expect(within(menu).queryByRole('button', { name: 'Delete profile' })).not.toBeInTheDocument(); // the only one
  await userEvent.click(within(menu).getByRole('button', { name: 'Clear ratings and history' }));
  await userEvent.click(within(menu).getByRole('button', { name: 'Yes, clear' }));
  await waitFor(() =>
    expect(calls.some(c => c.method === 'DELETE' && c.path === '/api/profiles/current/data')).toBe(true),
  );
  expect(await within(menu).findByText('Ratings and history cleared')).toBeInTheDocument();
});

test('a 401 (every profile has a PIN) shows the profile picker', async () => {
  mockFetch({
    'GET /api/state': () => [401, { error: 'Choose a profile to continue' }],
    'GET /api/profiles': () => [200, { profiles: [PROFILES[1]], current: null, chosen: false }],
  });
  render(<App />);
  expect(await screen.findByRole('heading', { name: 'Who’s watching?' })).toBeInTheDocument();
});

test('the details sheet adds the local model’s explanation when one is available', async () => {
  const { calls } = setup(
    () => appState({ profile: { ...ME, count: 1 }, llm: { available: true, name: 'local LLM', message: 'Ready' } }),
    {
      'POST /api/explain': () => [
        200,
        { id: 'm1', narration: 'Alpha is quiet, which suits you.', note: 'Written by a language model' },
      ],
    },
  );
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  await userEvent.click(screen.getByRole('button', { name: 'Why this pick' }));
  const sheet = screen.getByRole('dialog', { name: 'Alpha' });
  expect(await within(sheet).findByText('Alpha is quiet, which suits you.')).toBeInTheDocument();
  expect(calls.find(c => c.path === '/api/explain')?.body).toMatchObject({ id: 'm1', session: { mood: 'any' } });
});

test('without a local model the sheet never asks for an explanation', async () => {
  const { calls } = setup(() => appState({ profile: { ...ME, count: 1 } }));
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  await userEvent.click(screen.getByRole('button', { name: 'Why this pick' }));
  expect(calls.some(c => c.path === '/api/explain')).toBe(false);
});

test('every request names the page’s profile, and a profile change sends the page back to the picker', async () => {
  const { calls } = setup(() => appState({ profile: { ...ME, id: 2, name: 'Sam', chosen: true } }));
  render(<App />);
  await screen.findByRole('heading', { level: 1, name: 'Alpha' });
  expect(calls.find(c => c.path === '/api/recommend')?.headers['X-Flicks-Profile']).toBe('2');
  window.dispatchEvent(new Event(PROFILE_CHANGED));
  expect(await screen.findByRole('heading', { name: 'Who’s watching?' })).toBeInTheDocument();
});
