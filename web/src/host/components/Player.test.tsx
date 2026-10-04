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
