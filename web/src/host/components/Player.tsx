import { type CSSProperties, type SyntheticEvent, useCallback, useEffect, useRef, useState } from 'react';

import { mediaUrl } from '../../api/flicks';
import type { PlayerState, Rating, TitleRef } from '../../api/types';
import { Icon } from '../../components/Icon';
import { RateButtons } from '../../components/RateButtons';
import { cx } from '../../lib/cx';
import { runtime } from '../../lib/format';
import { prefersReducedMotion } from '../../lib/motion';
import { clockAfter } from '../../lib/useNow';

const SAVE_EVERY_MS = 10_000;
const CHROME_HIDE_MS = 2500;
const MEDIA_ERR_SRC_NOT_SUPPORTED = 4; // HTMLMediaElement.error.code (spec value; not every environment defines MediaError)
const UP_NEXT_SECONDS = 10;
/** Paused this long, the screen becomes an intermission card. */
const INTERMISSION_MS = 5 * 60_000;
/** The film leader before a film starts from the beginning: 3, 2, 1, each this long. */
const LEADER_STEP_MS = 800;

interface PlayerProps {
  item: TitleRef;
  startAt: number;
  /** Count in with a few frames of film leader before playing (starting from the beginning). */
  leader?: boolean;
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
  leader = false,
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
  const [counting, setCounting] = useState(() => leader && !prefersReducedMotion());
  const [intermission, setIntermission] = useState<{ position: number; duration: number; ends: string } | null>(null);
  const intermissionTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(intermissionTimer.current), []);

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
    autoPlay: !counting,
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
      clearTimeout(intermissionTimer.current);
      setIntermission(null);
      setEnded(false);
      setAutoplayBlocked(false);
      showChrome();
      onPlayback?.('playing');
    },
    onPause: (event: SyntheticEvent<HTMLMediaElement>) => {
      save();
      setChromeVisible(true);
      onPlayback?.('paused');
      const node = event.currentTarget;
      clearTimeout(intermissionTimer.current);
      if (!node.ended && Number.isFinite(node.duration)) {
        intermissionTimer.current = setTimeout(
          () =>
            setIntermission({
              position: node.currentTime,
              duration: node.duration,
              ends: clockAfter(Date.now(), (node.duration - node.currentTime) / 60),
            }),
          INTERMISSION_MS,
        );
      }
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
      {counting && (
        <Leader
          title={item.title}
          onDone={() => {
            setCounting(false);
            play();
          }}
        />
      )}
      {intermission && <Intermission item={item} {...intermission} onResume={play} />}
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

/** A few frames of film leader: 3, 2, 1, with the white "two-pop" frame, then the film. */
function Leader({ title, onDone }: { title: string; onDone: () => void }) {
  const [count, setCount] = useState(3);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });
  useEffect(() => {
    const timer = setTimeout(() => (count > 1 ? setCount(count - 1) : done.current()), LEADER_STEP_MS);
    return () => clearTimeout(timer);
  }, [count]);
  return (
    <div className={cx('leader', count === 1 && 'leader-pop')} aria-hidden="true">
      <div className="leader-reel">
        <span>{count}</span>
      </div>
      <p>{title}</p>
    </div>
  );
}

/** Paused for a while: an intermission card with what's left, when it would end, and a way back in. */
function Intermission({
  item,
  position,
  duration,
  ends,
  onResume,
}: {
  item: TitleRef;
  position: number;
  duration: number;
  /** When the film would end if resumed now ("9:42 pm"). */
  ends: string;
  onResume: () => void;
}) {
  const left = duration - position;
  const minutes = Math.max(1, Math.round(left / 60));
  // A bulb per ten minutes of the film (at most 24): outlined for what you've seen, lit for what's left.
  const slots = Math.min(24, Math.max(1, Math.ceil(duration / 600)));
  const seen = Math.floor((slots * position) / duration);
  return (
    <div className="intermission" role="region" aria-label="Intermission">
      <h2>Intermission</h2>
      <p>
        {item.title} has {runtime(minutes)} left. Resume now and it ends at {ends}.
      </p>
      <span className="bulbs" aria-hidden="true">
        {Array.from({ length: slots }, (_, k) => (
          <i key={k} className={k < seen ? 'bulb seen' : 'bulb on'} style={{ '--i': k } as CSSProperties} />
        ))}
      </span>
      <button type="button" className="button button-primary" onClick={onResume}>
        <Icon name="play" />
        Resume
      </button>
    </div>
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
