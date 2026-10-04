import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach } from 'vitest';

import type { Session } from '../../api/types';
import { mockFetch } from '../../test/fetchMock';
import { useCouchHost } from '../hooks/useCouchHost';
import { DEFAULT_SESSION } from '../session';
import { CouchPanel } from './CouchPanel';

const live = {
  active: true,
  version: 1,
  code: 'K7QX2MPA',
  url: 'http://192.168.1.23:8770/join',
  join_url: 'http://192.168.1.23:8770/join#K7QX2MPA',
  items: [],
  revealed: false,
  results: null,
  expires_in: 100,
  player: { id: null, state: 'stopped', by: null },
  progress: [{ name: 'Sam', voted: 0, total: 2 }],
};

function Harness({ session = DEFAULT_SESSION }: { session?: Session }) {
  const couch = useCouchHost(true);
  return <CouchPanel couch={couch} session={session} />;
}

afterEach(() => {
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
});

test('a tab opened in the background still shows the running session', async () => {
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  mockFetch({ 'GET /api/couch': () => [200, live] });
  render(<Harness />);
  expect(await screen.findByText('K7QX2MPA')).toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'QR code to join this couch session' })).toHaveAttribute(
    'src',
    '/api/couch/qr.svg?code=K7QX2MPA',
  );
  expect(screen.getByText('Sam: 0 of 2')).toBeInTheDocument();
});

test('starting a session sends the current scene', async () => {
  const { calls } = mockFetch({
    'GET /api/couch': () => [200, { active: false }],
    'POST /api/couch/start': () => [200, live],
  });
  const session = { ...DEFAULT_SESSION, mood: 'relaxing' as const, minutes: 100 };
  render(<Harness session={session} />);
  await userEvent.click(await screen.findByRole('button', { name: 'Start a couch session' }));
  expect(await screen.findByText('K7QX2MPA')).toBeInTheDocument();
  expect(calls.find(c => c.path === '/api/couch/start')?.body).toEqual({ session });
});
