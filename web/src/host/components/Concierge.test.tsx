import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, vi } from 'vitest';

import { flicksApi } from '../../api/flicks';
import type { ConciergeEvent } from '../../api/types';
import { ALPHA, BETA, GAMMA, pick } from '../../test/fixtures';
import { LibraryContext } from '../library';
import { DEFAULT_SESSION } from '../session';
import { Concierge } from './Concierge';

afterEach(() => vi.restoreAllMocks());

test('a quick reply, a question, then three picks that open and apply', async () => {
  const replies: ConciergeEvent[][] = [
    [
      { understood: ['Comedy', 'Relaxing'], patch: { mood: 'relaxing' } },
      { delta: 'How much time ' },
      { delta: 'do you have?' },
      { done: true, step: 'time', text: 'How much time do you have?', model: true },
    ],
    [
      { understood: ['Comedy', 'Relaxing', 'Up to 90 min'], patch: { mood: 'relaxing', minutes: 90 } },
      { picks: [pick(ALPHA), pick(BETA), pick(GAMMA)], session: { ...DEFAULT_SESSION, mood: 'relaxing', minutes: 90 } },
      { done: true, step: 'picks', text: 'Here are three for tonight: Alpha, Beta and Gamma.', model: false },
    ],
  ];
  const ask = vi.spyOn(flicksApi, 'concierge').mockImplementation(async (_query, onEvent) => {
    for (const event of replies.shift() ?? []) onEvent(event);
  });
  const onOpen = vi.fn();
  const onApply = vi.fn();
  const library = {
    posters: new Set<string>(),
    media: new Map(),
    feedback: {},
    progress: new Map(),
    rate: vi.fn(),
    openDetails: vi.fn(),
    play: vi.fn(),
  };
  render(
    <LibraryContext.Provider value={library}>
      <Concierge session={DEFAULT_SESSION} onOpen={onOpen} onApply={onApply} />
    </LibraryContext.Provider>,
  );

  await userEvent.click(screen.getByRole('button', { name: 'Chat with Flicks to find something to watch' }));
  expect(screen.getByText('Hi! What are you in the mood for tonight?')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Cozy and funny' }));
  expect(await screen.findByText('How much time do you have?')).toBeInTheDocument();
  expect(screen.getByRole('list', { name: 'What Flicks understood' })).toHaveTextContent('ComedyRelaxing');

  await userEvent.type(screen.getByRole('textbox', { name: 'Message Flicks' }), 'about 90 minutes{Enter}');
  expect(await screen.findByText('Here are three for tonight: Alpha, Beta and Gamma.')).toBeInTheDocument();
  expect(ask).toHaveBeenLastCalledWith(
    expect.objectContaining({
      messages: [
        { role: 'assistant', text: 'Hi! What are you in the mood for tonight?' },
        { role: 'user', text: 'Cozy and funny' },
        { role: 'assistant', text: 'How much time do you have?' },
        { role: 'user', text: 'about 90 minutes' },
      ],
      shown: [],
    }),
    expect.any(Function),
    expect.any(AbortSignal),
  );

  await userEvent.click(screen.getByRole('button', { name: /Beta/ }));
  expect(onOpen).toHaveBeenCalledWith(BETA);
  await userEvent.click(screen.getByRole('button', { name: 'Use these settings on Home' }));
  expect(onApply).toHaveBeenCalledWith({ ...DEFAULT_SESSION, mood: 'relaxing', minutes: 90 });
  expect(screen.getByRole('button', { name: 'Show me others' })).toBeInTheDocument();
});
