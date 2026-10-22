import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, vi } from 'vitest';

import { flicksApi } from '../../api/flicks';
import type { AskTitleEvent } from '../../api/types';
import { ALPHA, SERIES } from '../../test/fixtures';
import { DEFAULT_SESSION } from '../session';
import { TitleChat } from './TitleChat';

afterEach(() => vi.restoreAllMocks());

/** askTitle that replays `events` as the server would stream them. */
function answer(...events: AskTitleEvent[]) {
  return vi.spyOn(flicksApi, 'askTitle').mockImplementation(async (_query, onEvent) => {
    for (const event of events) onEvent(event);
  });
}

test('an answer streams in, with its timing, and follow-ups send the earlier turns', async () => {
  const ask = answer(
    { delta: 'Alpha stars ' },
    { delta: 'Sam Rockwell.' },
    { done: true, ok: true, answer: 'Alpha stars Sam Rockwell.' },
  );
  render(<TitleChat item={ALPHA} session={DEFAULT_SESSION} picked />);
  await userEvent.click(screen.getByRole('button', { name: 'Who is in it?' }));
  expect(await screen.findByText('Alpha stars Sam Rockwell.')).toBeInTheDocument();
  expect(screen.getByText(/answered in .* s · on this device/)).toBeInTheDocument();

  await userEvent.type(screen.getByRole('textbox', { name: 'Ask a question about Alpha' }), 'Who directed it?{Enter}');
  expect(ask).toHaveBeenLastCalledWith(
    {
      id: 'm1',
      question: 'Who directed it?',
      session: DEFAULT_SESSION,
      history: [{ question: 'Who is in it?', answer: 'Alpha stars Sam Rockwell.' }],
    },
    expect.any(Function),
    expect.any(AbortSignal),
  );
});

test('a withdrawn answer is replaced by the reason, and series get their own suggestions', async () => {
  answer(
    { delta: 'Try Blade Runner.' },
    { done: true, ok: false, note: 'The answer named a title Flicks did not give it' },
  );
  render(<TitleChat item={SERIES} session={DEFAULT_SESSION} picked={false} />);
  expect(screen.queryByRole('button', { name: 'Why this pick?' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'How many seasons are there?' }));
  expect(await screen.findByText('The answer named a title Flicks did not give it')).toBeInTheDocument();
  expect(screen.queryByText('Try Blade Runner.')).not.toBeInTheDocument();
});
