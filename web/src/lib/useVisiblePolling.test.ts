import { act, renderHook } from '@testing-library/react';
import { vi } from 'vitest';

import { useVisiblePolling } from './useVisiblePolling';

afterEach(() => vi.useRealTimers());

test('polls at once, then on the interval; a new interval reschedules without an immediate poll', async () => {
  vi.useFakeTimers();
  const poll = vi.fn();
  const { rerender, unmount } = renderHook(({ ms }) => useVisiblePolling(poll, true, ms), {
    initialProps: { ms: 15000 },
  });
  expect(poll).toHaveBeenCalledTimes(1);
  await act(() => vi.advanceTimersByTimeAsync(14000));
  expect(poll).toHaveBeenCalledTimes(1);
  rerender({ ms: 1500 }); // a session started: speed up, but do not overwrite the host's own state now
  expect(poll).toHaveBeenCalledTimes(1);
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(poll).toHaveBeenCalledTimes(2);
  await act(() => vi.advanceTimersByTimeAsync(3000));
  expect(poll).toHaveBeenCalledTimes(4);
  unmount();
  await act(() => vi.advanceTimersByTimeAsync(10000));
  expect(poll).toHaveBeenCalledTimes(4);
});

test('rescheduling while a poll is in flight never leaves two chains running', async () => {
  vi.useFakeTimers();
  let release: () => void = () => undefined;
  const poll = vi.fn(() => new Promise<void>(resolve => (release = resolve)));
  const { rerender, unmount } = renderHook(({ ms }) => useVisiblePolling(poll, true, ms), {
    initialProps: { ms: 1000 },
  });
  release(); // the immediate load
  await act(() => vi.advanceTimersByTimeAsync(1000)); // a timed poll starts and stays in flight
  expect(poll).toHaveBeenCalledTimes(2);
  rerender({ ms: 5000 }); // reschedule while it is in flight
  await act(async () => release()); // the old poll returns: it must not schedule a second chain
  await act(() => vi.advanceTimersByTimeAsync(5000));
  expect(poll).toHaveBeenCalledTimes(3);
  release();
  await act(() => vi.advanceTimersByTimeAsync(5000));
  expect(poll).toHaveBeenCalledTimes(4); // one poll per interval: a single chain
  unmount();
});
