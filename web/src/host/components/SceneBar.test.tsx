import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import type { Mode, Session } from '../../api/types';
import { spokenTime } from '../../lib/format';
import { DEFAULT_SESSION } from '../session';
import { SceneBar } from './SceneBar';

function Harness({ onTaste, series }: { onTaste?: () => void; series?: boolean }) {
  const [session, setSession] = useState<Session>(DEFAULT_SESSION);
  const [mode, setMode] = useState<Mode>('session');
  return (
    <>
      <SceneBar
        session={session}
        mode={mode}
        genres={['drama', 'horror']}
        series={series}
        onSession={setSession}
        onMode={setMode}
        onTaste={onTaste}
      />
      <output data-testid="session">{JSON.stringify({ ...session, mode })}</output>
    </>
  );
}
const state = () => JSON.parse(screen.getByTestId('session').textContent ?? '{}') as Session & { mode: Mode };

test('the scene reads as a sentence, and each word opens its choices', async () => {
  render(<Harness />);
  expect(screen.getByText(/I have/)).toHaveTextContent('I have 2 hours for something any mood, balanced.');
  await userEvent.click(screen.getByRole('button', { name: 'Time: 2 hours. Change' }));
  await userEvent.click(screen.getByRole('button', { name: '1h 30m' }));
  expect(screen.getByRole('button', { name: 'Time: 1½ hours. Change' })).toHaveAttribute('aria-expanded', 'true');
  await userEvent.click(screen.getByRole('button', { name: 'Energy: balanced. Change' }));
  await userEvent.click(screen.getByRole('radio', { name: 'Gentle' }));
  expect(state()).toMatchObject({ minutes: 90, intensity: 0.2 });
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('radiogroup', { name: 'Energy' })).not.toBeInTheDocument();
});

test('advanced settings wait behind More, which counts what was changed there', async () => {
  const onTaste = vi.fn();
  render(<Harness onTaste={onTaste} />);
  expect(screen.queryByRole('slider', { name: /Discovery/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'More options' }));
  fireEvent.change(screen.getByRole('slider', { name: /Discovery/ }), { target: { value: '80' } });
  await userEvent.click(screen.getByRole('button', { name: 'Horror' }));
  await userEvent.click(screen.getByRole('radio', { name: 'Taste only' }));
  expect(screen.getByRole('button', { name: /Fewer options/ })).toHaveTextContent('3');
  await userEvent.click(screen.getByRole('button', { name: 'Tune how picks are scored' }));
  expect(onTaste).toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Reset scene' }));
  expect(state()).toMatchObject({ novelty: 0.3, excluded_genres: [], mode: 'session' });
});

test('time is said the way people say it', () => {
  expect([45, 60, 90, 120, 150, 100].map(spokenTime)).toEqual([
    '45 minutes',
    '1 hour',
    '1½ hours',
    '2 hours',
    '2½ hours',
    '1h 40m',
  ]);
});

test('with series loaded, the sentence also asks for a film, a series or either', async () => {
  render(<Harness series />);
  expect(screen.getByText(/I have/)).toHaveTextContent(
    'I have 2 hours for something any mood, balanced, film or series.',
  );
  await userEvent.click(screen.getByRole('button', { name: 'Films or series: film or series. Change' }));
  await userEvent.click(screen.getByRole('radio', { name: 'Series' }));
  expect(state()).toMatchObject({ kind: 'series' });
  expect(screen.getByText(/I have/)).toHaveTextContent('balanced, a series.');
  await userEvent.click(screen.getByRole('button', { name: 'Reset scene' }));
  expect(state()).toMatchObject({ kind: 'any' });
});
