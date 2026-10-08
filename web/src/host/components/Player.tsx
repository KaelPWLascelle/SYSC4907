import { type SyntheticEvent, useCallback, useEffect, useRef, useState } from 'react';

import { mediaUrl } from '../../api/flicks';
import type { PlayerState, TitleRef } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { cx } from '../../lib/cx';

const SAVE_EVERY_MS = 10_000;
const CHROME_HIDE_MS = 2500;
const MEDIA_ERR_SRC_NOT_SUPPORTED = 4; // HTMLMediaElement.error.code (spec value; not every environment defines MediaError)

interface PlayerProps {
  item: TitleRef;
  startAt: number;
  directPlay: boolean;
  /** A podcast episode: an audio player over the title's art instead of a video. */
  audio?: boolean;
  /** Where a remote title streams from (through Flicks), for error messages; null for local files. */
  streamedFrom?: string | null;
  /** Couch-mode remote commands for this title; applied whenever `version` changes. */
  remote: { state: PlayerState['state']; version: number } | null;
  onProgress: (position: number, duration: number) => void;
  onPlayback?: (state: 'playing' | 'paused') => void;
  onClose: () => void;
}

/** Full-screen playback over HTTP range requests, of a local file or a stream relayed by Flicks (ADR 0005, 0011). */
export function Player({
  item,
  startAt,
  directPlay,
  audio = false,
  streamedFrom = null,
  remote,
  onProgress,
  onPlayback,
  onClose,
}: PlayerProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const video = useRef<HTMLMediaElement | null>(null);
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
      if (video.current && !video.current.paused && !audio) setChromeVisible(false);
    }, CHROME_HIDE_MS);
  };
  useEffect(() => () => clearTimeout(hideTimer.current), []);

  // The same element behaviour for <video> and <audio>.
  const media = {
    ref: (node: HTMLMediaElement | null) => {
      video.current = node;
    },
    src: mediaUrl(item.id),
    controls: true,
    autoPlay: true,
    onLoadedMetadata: (event: SyntheticEvent<HTMLMediaElement>) => {
      const node = event.currentTarget;
      // Whether to resume is decided once, by the server's `resumable` rule; only guard a stale position
      // past the end of the file (e.g. the file was replaced with a shorter cut).
      if (startAt > 0 && startAt < node.duration) node.currentTime = startAt;
    },
    onTimeUpdate: () => {
      if (Date.now() - lastSave.current >= SAVE_EVERY_MS) save();
    },
    onPlay: () => {
      setAutoplayBlocked(false);
      showChrome();
      onPlayback?.('playing');
    },
    onPause: () => {
      save();
      setChromeVisible(true);
      onPlayback?.('paused');
    },
    onEnded: save,
    onError: (event: SyntheticEvent<HTMLMediaElement>) => {
      const code = event.currentTarget.error?.code;
      if (streamedFrom) {
        setError(`Couldn’t stream this from ${streamedFrom}. Check your internet connection and try again.`);
        return;
      }
      setError(
        code === MEDIA_ERR_SRC_NOT_SUPPORTED
          ? audio
            ? 'This browser can’t play this episode’s audio format.'
            : `This browser can’t play this file${directPlay ? '' : ' (MKV or MOV)'}. Convert it to MP4 (H.264/AAC) or WebM.`
          : audio
            ? 'The episode could not be played. Try removing the download and downloading it again.'
            : 'The file could not be played. Check that it is still in your media folder.',
      );
    },
  };

  return (
    <dialog
      ref={dialog}
      className={cx('player', audio && 'player-audio', !chromeVisible && 'player-idle')}
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
          <p className="eyebrow">{audio ? 'Now listening' : 'Now playing'}</p>
          <h2>{item.title}</h2>
        </div>
        <button type="button" className="round" aria-label="Close player" onClick={close}>
          <Icon name="close" />
        </button>
      </header>
      {audio ? (
        <div className="player-listen">
          <Poster item={item} hasPoster={false} className="poster poster-listen" eager />
          <audio className="player-audio-controls" {...media} />
        </div>
      ) : (
        <video className="player-video" playsInline {...media} />
      )}
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
