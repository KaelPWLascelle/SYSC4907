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

test('with a model: any question, titles without a scene, and follow-ups name the last titles', async () => {
  const replies: ConciergeEvent[][] = [
    [
      { understood: ['“Tom Hanks”'], patch: {} },
      { picks: [pick(ALPHA), pick(BETA)] },
      { delta: 'Alpha stars Tom Hanks.' },
      { delta: ' Beta does too.' },
      { done: true, step: 'picks', text: 'Alpha stars Tom Hanks. Beta does too.', model: true },
    ],
    [
      { understood: [], patch: {} },
      { picks: [pick(ALPHA), pick(BETA)] },
      { delta: 'Beta is the shortest.' },
      { done: true, step: 'picks', text: 'Beta is the shortest.', model: true },
    ],
  ];
  const ask = vi.spyOn(flicksApi, 'concierge').mockImplementation(async (_query, onEvent) => {
    for (const event of replies.shift() ?? []) onEvent(event);
  });
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
      <Concierge session={DEFAULT_SESSION} onOpen={vi.fn()} onApply={vi.fn()} open />
    </LibraryContext.Provider>,
  );

  await userEvent.click(screen.getByRole('button', { name: 'Chat with Flicks to find something to watch' }));
  expect(screen.getByText(/Ask me for a mood, a person/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Tom Hanks films' }));
  expect(await screen.findByText('Alpha stars Tom Hanks. Beta does too.')).toBeInTheDocument();
  expect(ask).toHaveBeenLastCalledWith(
    expect.objectContaining({ previous: [] }),
    expect.any(Function),
    expect.any(AbortSignal),
  );
  // Search results are not a scene for Home.
  expect(screen.queryByRole('button', { name: 'Use these settings on Home' })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole('button', { name: 'Which is shortest?' }));
  expect(await screen.findByText('Beta is the shortest.')).toBeInTheDocument();
  expect(ask).toHaveBeenLastCalledWith(
    expect.objectContaining({ previous: [ALPHA.id, BETA.id] }),
    expect.any(Function),
    expect.any(AbortSignal),
  );
});
