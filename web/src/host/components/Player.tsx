import { type SyntheticEvent, useCallback, useEffect, useRef, useState } from 'react';

import { mediaUrl } from '../../api/flicks';
import type { PlayerState, Rating, TitleRef } from '../../api/types';
import { Icon } from '../../components/Icon';
import { RateButtons } from '../../components/RateButtons';
import { cx } from '../../lib/cx';
import { prefersReducedMotion } from '../../lib/motion';

const SAVE_EVERY_MS = 10_000;
const CHROME_HIDE_MS = 2500;
const MEDIA_ERR_SRC_NOT_SUPPORTED = 4; // HTMLMediaElement.error.code (spec value; not every environment defines MediaError)
const UP_NEXT_SECONDS = 10;

interface PlayerProps {
  item: TitleRef;
  startAt: number;
  directPlay: boolean;
  /** Where a remote title streams from (through Flicks), for error messages; null for local files. */
  streamedFrom?: string | null;
  /** Couch-mode remote commands for this title; applied whenever `version` changes. */
  remote: { state: PlayerState['state']; version: number } | null;
  onProgress: (position: number, duration: number) => void;
  onPlayback?: (state: 'playing' | 'paused') => void;
  onClose: () => void;
  /** When a film ends: its rating, and the next pick to offer (null: nothing playable is left). */
  rating?: Rating;
  onRate?: (value: Rating | 0) => void;
  upNext?: TitleRef | null;
  onUpNext?: (item: TitleRef) => void;
}

/** Full-screen playback over HTTP range requests, of a local file or a stream relayed by Flicks (ADR 0005, 0011). */
export function Player({
  item,
  startAt,
  directPlay,
  streamedFrom = null,
  remote,
  onProgress,
  onPlayback,
  onClose,
  rating,
  onRate,
  upNext = null,
  onUpNext,
}: PlayerProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const video = useRef<HTMLMediaElement | null>(null);
  const lastSave = useRef(0);
  const [error, setError] = useState('');
  const [autoplayBlocked, setAutoplayBlocked] = useState(false);
  const [chromeVisible, setChromeVisible] = useState(true);
  const [ended, setEnded] = useState(false);
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
      setEnded(false);
      setAutoplayBlocked(false);
      showChrome();
      onPlayback?.('playing');
    },
    onPause: () => {
      save();
      setChromeVisible(true);
      onPlayback?.('paused');
    },
    onEnded: () => {
      save();
      setChromeVisible(true);
      if (remote === null) setEnded(true); // a couch remote decides what plays next
    },
    onError: (event: SyntheticEvent<HTMLMediaElement>) => {
      const code = event.currentTarget.error?.code;
      if (streamedFrom) {
        setError(`Couldn’t stream this from ${streamedFrom}. Check your internet connection and try again.`);
        return;
      }
      setError(
        code === MEDIA_ERR_SRC_NOT_SUPPORTED
          ? `This browser can’t play this file${directPlay ? '' : ' (MKV or MOV)'}. Convert it to MP4 (H.264/AAC) or WebM.`
          : 'The file could not be played. Check that it is still in your media folder.',
      );
    },
  };

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
      <video className="player-video" playsInline {...media} />
      {ended && (
        <EndCard
          item={item}
          rating={rating}
          onRate={onRate}
          upNext={upNext}
          onUpNext={onUpNext}
          onReplay={() => {
            setEnded(false);
            if (video.current) video.current.currentTime = 0;
            play();
          }}
        />
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

interface EndCardProps {
  item: TitleRef;
  rating?: Rating;
  onRate?: (value: Rating | 0) => void;
  upNext: TitleRef | null;
  onUpNext?: (item: TitleRef) => void;
  onReplay: () => void;
}

/** After a film: one tap to rate it, and the next pick, which starts on its own after a countdown. */
function EndCard({ item, rating, onRate, upNext, onUpNext, onReplay }: EndCardProps) {
  // No countdown when the viewer asked for less motion: the next film waits for a press.
  const [seconds, setSeconds] = useState<number | null>(() =>
    upNext && onUpNext && !prefersReducedMotion() ? UP_NEXT_SECONDS : null,
  );
  useEffect(() => {
    if (seconds === null || !upNext || !onUpNext) return;
    if (seconds <= 0) {
      onUpNext(upNext);
      return;
    }
    const timer = setTimeout(() => setSeconds(seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [seconds, upNext, onUpNext]);

  return (
    <div className="player-end" role="region" aria-label="Finished">
      {onRate && (
        <div className="player-end-rate">
          <p className="eyebrow">Finished</p>
          <h3>How was {item.title}?</h3>
          <RateButtons title={item.title} rating={rating} large onRate={onRate} />
        </div>
      )}
      {upNext && onUpNext ? (
        <div className="player-end-next">
          <p className="eyebrow">Up next for you</p>
          <h3>{upNext.title}</h3>
          <p className="fine" aria-live="polite">
            {seconds === null ? 'Ready when you are.' : `Starts in ${seconds} s`}
          </p>
          <div className="details-actions">
            <button type="button" className="button button-primary" onClick={() => onUpNext(upNext)}>
              <Icon name="play" />
              Play now
            </button>
            {seconds !== null ? (
              <button type="button" className="button button-quiet" onClick={() => setSeconds(null)}>
                Cancel
              </button>
            ) : (
              <button type="button" className="button button-quiet" onClick={onReplay}>
                <Icon name="replay" />
                Watch again
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="player-end-next">
          <p className="fine">Nothing else playable fits this scene.</p>
          <button type="button" className="button button-quiet" onClick={onReplay}>
            <Icon name="replay" />
            Watch again
          </button>
        </div>
      )}
    </div>
  );
}
