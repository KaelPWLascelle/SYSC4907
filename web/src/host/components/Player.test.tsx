import { act, fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { content } from '../../test/fixtures';
import { Player } from './Player';

function video() {
  const node = document.querySelector('video');
  if (!node) throw new Error('no video element');
  return node;
}

function setMedia(
  node: HTMLVideoElement,
  props: { duration?: number; currentTime?: number; paused?: boolean; ended?: boolean; errorCode?: number },
) {
  for (const [key, value] of Object.entries({
    duration: props.duration,
    currentTime: props.currentTime,
    paused: props.paused,
    ended: props.ended,
    error: props.errorCode === undefined ? undefined : { code: props.errorCode },
  })) {
    if (value !== undefined) Object.defineProperty(node, key, { configurable: true, writable: true, value });
  }
}

const item = content('m1', 'Alpha');

test('resumes from the saved position and saves progress at most every 10 s, and on pause', () => {
  vi.useFakeTimers({ toFake: ['Date'] });
  const onProgress = vi.fn();
  render(<Player item={item} startAt={120} directPlay remote={null} onProgress={onProgress} onClose={() => {}} />);
  const node = video();
  setMedia(node, { duration: 600, currentTime: 0 });
  fireEvent.loadedMetadata(node);
  expect(node.currentTime).toBe(120);

  setMedia(node, { currentTime: 125 });
  fireEvent.timeUpdate(node); // first update saves (nothing saved yet)
  expect(onProgress).toHaveBeenLastCalledWith(125, 600);
  setMedia(node, { currentTime: 130 });
  fireEvent.timeUpdate(node);
  expect(onProgress).toHaveBeenCalledTimes(1); // throttled
  vi.setSystemTime(Date.now() + 10_000);
  setMedia(node, { currentTime: 140 });
  fireEvent.timeUpdate(node);
  expect(onProgress).toHaveBeenCalledTimes(2);
  setMedia(node, { currentTime: 141, paused: true });
  fireEvent.pause(node);
  expect(onProgress).toHaveBeenLastCalledWith(141, 600);
});

test('ignores a saved position past the end of the file', () => {
  render(<Player item={item} startAt={700} directPlay remote={null} onProgress={() => {}} onClose={() => {}} />);
  const node = video();
  setMedia(node, { duration: 600, currentTime: 0 });
  fireEvent.loadedMetadata(node);
  expect(node.currentTime).toBe(0);
});

test('remote commands pause and close; closing saves first', () => {
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause');
  const onClose = vi.fn();
  const onProgress = vi.fn();
  const { rerender } = render(
    <Player
      item={item}
      startAt={0}
      directPlay
      remote={{ state: 'playing', version: 1 }}
      onProgress={onProgress}
      onClose={onClose}
    />,
  );
  setMedia(video(), { duration: 600, currentTime: 42 });
  rerender(
    <Player
      item={item}
      startAt={0}
      directPlay
      remote={{ state: 'paused', version: 2 }}
      onProgress={onProgress}
      onClose={onClose}
    />,
  );
  expect(pause).toHaveBeenCalled();
  rerender(
    <Player
      item={item}
      startAt={0}
      directPlay
      remote={{ state: 'stopped', version: 3 }}
      onProgress={onProgress}
      onClose={onClose}
    />,
  );
  expect(onProgress).toHaveBeenLastCalledWith(42, 600);
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('an unsupported format explains what to do', () => {
  render(<Player item={item} startAt={0} directPlay={false} remote={null} onProgress={() => {}} onClose={() => {}} />);
  const node = video();
  setMedia(node, { errorCode: 4 });
  act(() => {
    fireEvent.error(node);
  });
  expect(screen.getByRole('alert')).toHaveTextContent(
    'This browser can’t play this file (MKV or MOV). Convert it to MP4',
  );
});

describe('when a film ends', () => {
  const next = content('m2', 'Beta');
  const ended = () => {
    const node = video();
    setMedia(node, { duration: 600, currentTime: 600, ended: true });
    fireEvent.ended(node);
  };

  test('asks for a rating and plays the next pick after a 10 s countdown', () => {
    vi.useFakeTimers();
    const onRate = vi.fn();
    const onUpNext = vi.fn();
    render(
      <Player
        item={item}
        startAt={0}
        directPlay
        remote={null}
        onProgress={() => {}}
        onClose={() => {}}
        onRate={onRate}
        upNext={next}
        onUpNext={onUpNext}
      />,
    );
    ended();
    expect(screen.getByRole('heading', { name: 'How was Alpha?' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Like: Alpha' }));
    expect(onRate).toHaveBeenCalledWith(1);
    expect(screen.getByText('Starts in 10 s')).toBeInTheDocument();
    for (let second = 0; second < 9; second += 1) act(() => vi.advanceTimersByTime(1000));
    expect(onUpNext).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1000));
    expect(onUpNext).toHaveBeenCalledWith(next);
  });

  test('Cancel stops the countdown; nothing starts on its own', () => {
    vi.useFakeTimers();
    const onUpNext = vi.fn();
    render(
      <Player
        item={item}
        startAt={0}
        directPlay
        remote={null}
        onProgress={() => {}}
        onClose={() => {}}
        upNext={next}
        onUpNext={onUpNext}
      />,
    );
    ended();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    act(() => vi.advanceTimersByTime(20_000));
    expect(onUpNext).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Play now' }));
    expect(onUpNext).toHaveBeenCalledWith(next);
  });

  test('with reduced motion there is no countdown, and nothing playable left offers a replay', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query }));
    vi.useFakeTimers();
    const onUpNext = vi.fn();
    const { unmount } = render(
      <Player
        item={item}
        startAt={0}
        directPlay
        remote={null}
        onProgress={() => {}}
        onClose={() => {}}
        upNext={next}
        onUpNext={onUpNext}
      />,
    );
    ended();
    expect(screen.getByText('Ready when you are.')).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(20_000));
    expect(onUpNext).not.toHaveBeenCalled();
    unmount();
    render(
      <Player
        item={item}
        startAt={0}
        directPlay
        remote={null}
        onProgress={() => {}}
        onClose={() => {}}
        upNext={null}
        onUpNext={onUpNext}
      />,
    );
    ended();
    expect(screen.getByText('Nothing else playable fits this scene.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Watch again' })).toBeInTheDocument();
  });

  test('a couch remote decides what plays next, so no end card', () => {
    render(
      <Player
        item={item}
        startAt={0}
        directPlay
        remote={{ state: 'playing', version: 1 }}
        onProgress={() => {}}
        onClose={() => {}}
        upNext={next}
        onUpNext={() => {}}
      />,
    );
    ended();
    expect(screen.queryByRole('region', { name: 'Finished' })).not.toBeInTheDocument();
  });
});
