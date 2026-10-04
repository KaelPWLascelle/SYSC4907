import { useCallback, useEffect, useRef, useState } from 'react';

import { mediaUrl } from '../../api/flicks';
import type { Content, PlayerState } from '../../api/types';
import { Icon } from '../../components/Icon';
import { cx } from '../../lib/cx';

const SAVE_EVERY_MS = 10_000;
const CHROME_HIDE_MS = 2500;
const MEDIA_ERR_SRC_NOT_SUPPORTED = 4; // HTMLMediaElement.error.code (spec value; not every environment defines MediaError)

interface PlayerProps {
  item: Content;
  startAt: number;
  directPlay: boolean;
  /** Couch-mode remote commands for this title; applied whenever `version` changes. */
  remote: { state: PlayerState['state']; version: number } | null;
  onProgress: (position: number, duration: number) => void;
  onPlayback?: (state: 'playing' | 'paused') => void;
  onClose: () => void;
}

/** Full-screen playback of a local file over HTTP range requests (docs/adr/0005-video-playback.md). */
export function Player({ item, startAt, directPlay, remote, onProgress, onPlayback, onClose }: PlayerProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const lastSave = useRef(0);
  const [error, setError] = useState('');
  const [autoplayBlocked, setAutoplayBlocked] = useState(false);
  const [chromeVisible, setChromeVisible] = useState(true);
  const hideTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const save = useCallback(() => {
    const node = video.current;
    if (!node || !Number.isFinite(node.duration) || node.duration <= 0) return;
    lastSave.current = Date.now();
    onProgress(node.ended ? node.duration : node.currentTime, node.duration);
  }, [onProgress]);

  const close = useCallback(() => {
    save();
    onClose();
  }, [save, onClose]);

  useEffect(() => {
    const node = dialog.current;
    if (node && !node.open) node.showModal();
  }, []);

  const play = useCallback(() => {
    video.current?.play().then(
      () => setAutoplayBlocked(false),
      () => setAutoplayBlocked(true), // no user gesture on this device (e.g. started from a phone)
    );
  }, []);

  // Apply each remote command once, when it changes; read the latest actions through a ref.
  const actions = useRef({ play, close });
  useEffect(() => {
    actions.current = { play, close };
  });
  const remoteState = remote?.state;
  const remoteVersion = remote?.version;
  useEffect(() => {
    if (remoteState === undefined) return;
    if (remoteState === 'playing') actions.current.play();
    else if (remoteState === 'paused') video.current?.pause();
    else actions.current.close();
  }, [remoteState, remoteVersion]);

  const showChrome = () => {
    setChromeVisible(true);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => {
      if (video.current && !video.current.paused) setChromeVisible(false);
    }, CHROME_HIDE_MS);
  };
  useEffect(() => () => clearTimeout(hideTimer.current), []);

  return (
    <dialog
      ref={dialog}
      className={cx('player', !chromeVisible && 'player-idle')}
      aria-label={`Playing ${item.title}`}
      onCancel={event => {
        event.preventDefault(); // Escape: save progress first, then close
        close();
      }}
      onMouseMove={showChrome}
      onKeyDown={event => {
        showChrome();
        if (event.key === 'f' && !event.metaKey && !event.ctrlKey) {
          if (document.fullscreenElement) void document.exitFullscreen();
          else void dialog.current?.requestFullscreen();
        }
      }}
    >
      <header className="player-bar">
        <div>
          <p className="eyebrow">Now playing</p>
          <h2>{item.title}</h2>
        </div>
        <button type="button" className="round" aria-label="Close player" onClick={close}>
          <Icon name="close" />
        </button>
      </header>
      <video
        ref={video}
        className="player-video"
        src={mediaUrl(item.id)}
        controls
        autoPlay
        playsInline
        onLoadedMetadata={event => {
          const node = event.currentTarget;
          // Whether to resume is decided once, by the server's `resumable` rule; only guard a stale position
          // past the end of the file (e.g. the file was replaced with a shorter cut).
          if (startAt > 0 && startAt < node.duration) node.currentTime = startAt;
        }}
        onTimeUpdate={() => {
          if (Date.now() - lastSave.current >= SAVE_EVERY_MS) save();
        }}
        onPlay={() => {
          setAutoplayBlocked(false);
          showChrome();
          onPlayback?.('playing');
        }}
        onPause={() => {
          save();
          setChromeVisible(true);
          onPlayback?.('paused');
        }}
        onEnded={save}
        onError={event => {
          const code = event.currentTarget.error?.code;
          setError(
            code === MEDIA_ERR_SRC_NOT_SUPPORTED
              ? `This browser can’t play this file${directPlay ? '' : ' (MKV or MOV)'}. Convert it to MP4 (H.264/AAC) or WebM.`
              : 'The file could not be played. Check that it is still in your media folder.',
          );
        }}
      />
      {(error || autoplayBlocked) && (
        <div className="player-message" role="alert">
          {error || (
            <button type="button" className="button button-primary" onClick={play}>
              <Icon name="play" />
              Press play to start
            </button>
          )}
        </div>
      )}
    </dialog>
  );
}
