import { useCallback, useEffect, useRef, useState } from 'react';

import { flicksApi, mediaUrl } from '../../api/flicks';
import type { DiscoverItem, Rating, Session } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { RateButtons } from '../../components/RateButtons';
import { capitalize, subtitle } from '../../lib/format';
import { prefersReducedMotion } from '../../lib/motion';
import { useLibrary } from '../library';

const PAGE = 8;
const SEEN_LIMIT = 300; // the server's cap: the newest are sent
const PREFETCH = 3; // fetch the next page this many cards before the end
const STREAM_LABELS: Record<DiscoverItem['stream'], string> = {
  for_you: 'For you',
  new: 'Something new',
  wildcard: 'Wildcard',
};
// YouTube's privacy-enhanced domain; the server's Content Security Policy allows frames from it alone.
const EMBED_ORIGIN = 'https://www.youtube-nocookie.com';
// How long to wait for the player to say whether a trailer plays before showing the frame anyway.
const TRAILER_TIMEOUT_MS = 8000;
// Player states that mean the trailer is there: playing, paused, buffering, cued.
const SHOWN_STATES = new Set([1, 2, 3, 5]);

// Trailers YouTube refused here (removed, embedding turned off, or blocked in this country), remembered
// in this browser so those films show their poster at once next time. Video IDs only.
const BLOCKED_KEY = 'flicks.trailers.unavailable';
const BLOCKED_LIMIT = 1000;
function blockedTrailers(): Set<string> {
  try {
    const value = JSON.parse(localStorage.getItem(BLOCKED_KEY) ?? '[]') as unknown;
    return new Set(Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []);
  } catch {
    return new Set();
  }
}
function rememberBlocked(video: string) {
  const blocked = [...blockedTrailers(), video].slice(-BLOCKED_LIMIT);
  try {
    localStorage.setItem(BLOCKED_KEY, JSON.stringify([...new Set(blocked)]));
  } catch {
    // Storage is unavailable: the card still falls back for this visit.
  }
}

const trailersKey = (profile: number | undefined) => `flicks.trailers.${profile ?? 0}`;
function trailersAllowed(profile: number | undefined) {
  try {
    return localStorage.getItem(trailersKey(profile)) === 'on';
  } catch {
    return false;
  }
}

interface DiscoverProps {
  session: Session;
  /** Films with a trailer on this server; 0 hides the online-trailers switch. */
  trailers: number;
  profileId?: number;
  /** Another player or sheet is open over the feed: show posters only. */
  paused: boolean;
  onClose: () => void;
}

/**
 * Discover: a vertical feed to react to, one film at a time (docs/adr/0016-discover.md). Likes and passes
 * are ordinary ratings, so they shape the next page and every other list. Media plays only on the card in
 * view: a preview of the film itself when it plays here, else a trailer if the viewer allowed them.
 * Mounted while open, so each opening starts a fresh feed for the scene as it is then.
 */
export function Discover({ session, trailers, profileId, paused, onClose }: DiscoverProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const feed = useRef<HTMLDivElement>(null);
  const library = useLibrary();
  const [items, setItems] = useState<DiscoverItem[]>([]);
  const [active, setActive] = useState(0);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const [online, setOnline] = useState(() => trailersAllowed(profileId));
  const [asking, setAsking] = useState(false);
  const [muted, setMuted] = useState(true);

  useEffect(() => {
    const node = dialog.current;
    if (node && !node.open) node.showModal();
  }, []);

  // More cards are wanted at the start and whenever the viewer nears the end. While they are wanted
  // (and nothing failed) one request is in flight: that is what "loading" means.
  const wantMore = !done && !error && (items.length === 0 || active >= items.length - PREFETCH);
  const loading = wantMore;
  useEffect(() => {
    if (!wantMore) return;
    const controller = new AbortController();
    const seen = items.slice(-SEEN_LIMIT).map(item => item.content.id);
    flicksApi.discover({ session, seen, online, limit: PAGE }, controller.signal).then(
      response => {
        setItems([...items, ...response.items]);
        setDone(response.items.length < PAGE);
      },
      (failure: unknown) => {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure));
      },
    );
    return () => controller.abort();
  }, [wantMore, items, online, session]);

  // The card most in view is the active one (and the only one that plays).
  useEffect(() => {
    const root = feed.current;
    if (!root || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(Number((entry.target as HTMLElement).dataset.index));
        }
      },
      { root, threshold: 0.6 },
    );
    root.querySelectorAll('.discover-card[data-index]').forEach(card => observer.observe(card));
    return () => observer.disconnect();
  }, [items]);

  const go = useCallback(
    (index: number) => {
      const target = Math.max(0, Math.min(index, items.length - 1));
      setActive(target);
      feed.current
        ?.querySelector(`[data-index="${target}"]`)
        ?.scrollIntoView?.({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
    },
    [items.length],
  );

  const rate = (item: DiscoverItem, value: Rating | 0) => {
    library.rate(item.content.id, value);
    if (value !== 0) go(items.indexOf(item) + 1); // reacted: on to the next
  };

  const setTrailers = (allow: boolean) => {
    setAsking(false);
    setOnline(allow);
    try {
      localStorage.setItem(trailersKey(profileId), allow ? 'on' : 'off');
    } catch {
      // Storage is unavailable (private window): the choice lasts for this visit.
    }
    // Cards already carry their trailer IDs, so the change shows at once; later pages prefer films with one.
  };

  const current = items[active];
  // Keys work wherever focus is (a button that just closed leaves it on the page), unless something
  // is open over the feed. Handlers are read through a ref so the listener stays put.
  const keys = useRef<(event: KeyboardEvent) => void>(() => undefined);
  useEffect(() => {
    keys.current = event => {
      if (paused || asking || event.metaKey || event.ctrlKey || event.altKey || !current) return;
      const key = event.key;
      if (key === 'ArrowDown' || key === 'j') go(active + 1);
      else if (key === 'ArrowUp' || key === 'k') go(active - 1);
      else if (key === 'l') rate(current, library.feedback[current.content.id] === 1 ? 0 : 1);
      else if (key === 'p') rate(current, library.feedback[current.content.id] === -1 ? 0 : -1);
      else return;
      event.preventDefault();
    };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => keys.current(event);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  return (
    <dialog ref={dialog} className="discover" aria-label="Discover" onClose={onClose}>
      <header className="discover-bar">
        <div>
          <p className="eyebrow">Discover</p>
          <p className="discover-hint">
            Like or pass to shape what comes next · <kbd>↑</kbd> <kbd>↓</kbd> move · <kbd>L</kbd> like · <kbd>P</kbd>{' '}
            pass
          </p>
        </div>
        <div className="discover-tools">
          {trailers > 0 && (
            <button
              type="button"
              className="chip"
              aria-pressed={online}
              onClick={() => (online ? setTrailers(false) : setAsking(true))}
            >
              Online trailers {online ? 'on' : 'off'}
            </button>
          )}
          <button type="button" className="round" aria-label="Close Discover" onClick={() => dialog.current?.close()}>
            <Icon name="close" />
          </button>
        </div>
      </header>
      {asking && (
        <div className="discover-consent" role="alertdialog" aria-labelledby="consent-title">
          <h2 id="consent-title">Play trailers from YouTube?</h2>
          <p>
            Trailers play in YouTube’s privacy-enhanced mode, only for the card on screen. YouTube will see your IP
            address and which trailers you play. Your ratings and history never leave this computer. Without trailers,
            Discover shows previews of films you can play here, and posters.
          </p>
          <div className="details-actions">
            <button type="button" className="button button-primary" onClick={() => setTrailers(true)}>
              Allow trailers
            </button>
            <button type="button" className="button button-quiet" onClick={() => setAsking(false)}>
              Not now
            </button>
          </div>
        </div>
      )}
      <div className="discover-feed" ref={feed} role="feed" aria-busy={loading} aria-label="Films to discover">
        {items.map((item, index) => (
          <Card
            key={item.content.id}
            item={item}
            index={index}
            total={done ? items.length : -1}
            playing={!paused && index === active}
            near={Math.abs(index - active) <= 2}
            online={online}
            muted={muted}
            onMute={() => setMuted(value => !value)}
            onRate={value => rate(item, value)}
          />
        ))}
        {(loading || error || (done && items.length === 0)) && (
          <div className="discover-card discover-status" role="status">
            {error ? (
              <>
                <p>Couldn’t load more: {error}</p>
                <button type="button" className="button button-quiet" onClick={() => setError('')}>
                  Try again
                </button>
              </>
            ) : loading ? (
              <p>Finding films…</p>
            ) : (
              <p>Nothing left to discover for this scene. Try a different mood, or clear a few ratings.</p>
            )}
          </div>
        )}
        {done && items.length > 0 && !loading && (
          <div className="discover-card discover-status">
            <p>You’ve seen everything for this scene.</p>
          </div>
        )}
      </div>
    </dialog>
  );
}

interface CardProps {
  item: DiscoverItem;
  index: number;
  /** Total cards once the feed has ended; -1 while it goes on. */
  total: number;
  playing: boolean;
  /** Within two cards of the one in view: load its poster now. */
  near: boolean;
  online: boolean;
  muted: boolean;
  onMute: () => void;
  onRate: (value: Rating | 0) => void;
}

function Card({ item, index, total, playing, near, online, muted, onMute, onRate }: CardProps) {
  const library = useLibrary();
  const { content, media } = item;
  const [unavailable, setUnavailable] = useState(false);
  const playable = library.media.has(content.id);
  const titleId = `discover-title-${content.id}`;
  return (
    <article
      className="discover-card"
      data-index={index}
      aria-labelledby={titleId}
      aria-posinset={index + 1}
      aria-setsize={total}
    >
      <div className="discover-media">
        {playing && (media.kind === 'file' || media.kind === 'stream') ? (
          <Preview id={content.id} muted={muted} onMute={onMute} />
        ) : playing && media.trailer && online && !unavailable && !blockedTrailers().has(media.trailer) ? (
          <Trailer
            video={media.trailer}
            title={content.title}
            onUnavailable={() => {
              rememberBlocked(media.trailer as string);
              setUnavailable(true);
            }}
          />
        ) : (
          <>
            <Poster
              item={content}
              hasPoster={library.posters.has(content.id)}
              className="poster discover-poster"
              eager={near}
            />
            {online && media.trailer && (unavailable || blockedTrailers().has(media.trailer)) && (
              <p className="discover-note">This trailer can’t be played here.</p>
            )}
          </>
        )}
      </div>
      <div className="discover-info">
        <p className="eyebrow">{STREAM_LABELS[item.stream]}</p>
        <h2 id={titleId}>{content.title}</h2>
        <p className="hero-meta">
          {subtitle(content)} · {content.genres.map(capitalize).join(' · ')}
        </p>
        <p className="discover-why">{item.why}</p>
        <p className="discover-description">{content.description}</p>
        <div className="discover-actions">
          <RateButtons title={content.title} rating={library.feedback[content.id]} large onRate={onRate} />
          {playable && (
            <button type="button" className="button button-primary" onClick={() => library.play(content)}>
              <Icon name="play" />
              Play film
            </button>
          )}
          <button type="button" className="button button-quiet" onClick={() => library.openDetails(content)}>
            <Icon name="info" />
            Details
          </button>
        </div>
      </div>
    </article>
  );
}

/** A silent preview of the film itself, from a tenth of the way in (past the titles), on the card in view. */
function Preview({ id, muted, onMute }: { id: string; muted: boolean; onMute: () => void }) {
  const reduced = prefersReducedMotion();
  return (
    <>
      <video
        className="discover-video"
        src={mediaUrl(id)}
        muted={muted}
        autoPlay={!reduced}
        controls={reduced}
        playsInline
        preload="metadata"
        onLoadedMetadata={event => {
          const node = event.currentTarget;
          if (Number.isFinite(node.duration) && node.duration > 120)
            node.currentTime = Math.min(node.duration / 10, 300);
        }}
      />
      <button
        type="button"
        className="round discover-mute"
        aria-label={muted ? 'Turn sound on' : 'Mute'}
        onClick={onMute}
      >
        <Icon name={muted ? 'volumeOff' : 'volumeUp'} />
      </button>
    </>
  );
}

/**
 * A YouTube trailer that reports back. With `enablejsapi`, the embedded player posts its state and errors
 * to this page; listening needs no YouTube script here (the CSP allows none). The frame stays hidden until
 * the trailer is there, so a trailer YouTube refuses (error 100, 101 or 150: removed, not embeddable, or
 * blocked in this country) never shows YouTube's error screen: the card falls back to its poster.
 */
function Trailer({ video, title, onUnavailable }: { video: string; title: string; onUnavailable: () => void }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [shown, setShown] = useState(false);
  const failed = useRef(onUnavailable);
  useEffect(() => {
    failed.current = onUnavailable;
  });
  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    let heard = false;
    // The player answers once it has been told someone is listening; repeat until it does.
    const listen = setInterval(() => {
      if (heard) clearInterval(listen);
      else
        node.contentWindow?.postMessage(
          JSON.stringify({ event: 'listening', id: video, channel: 'widget' }),
          EMBED_ORIGIN,
        );
    }, 250);
    const fallback = setTimeout(() => setShown(true), TRAILER_TIMEOUT_MS);
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== EMBED_ORIGIN || event.source !== node.contentWindow || typeof event.data !== 'string')
        return;
      let message: { event?: string; info?: unknown };
      try {
        message = JSON.parse(event.data) as typeof message;
      } catch {
        return;
      }
      heard = true;
      if (message.event === 'onError') {
        clearTimeout(fallback);
        failed.current();
      } else if (message.event === 'infoDelivery' || message.event === 'initialDelivery') {
        const state = (message.info as { playerState?: number } | null)?.playerState;
        if (state !== undefined && SHOWN_STATES.has(state)) {
          clearTimeout(fallback);
          setShown(true);
        }
      }
    };
    window.addEventListener('message', onMessage);
    return () => {
      clearInterval(listen);
      clearTimeout(fallback);
      window.removeEventListener('message', onMessage);
    };
  }, [video]);
  const params = new URLSearchParams({
    autoplay: prefersReducedMotion() ? '0' : '1',
    mute: '1',
    playsinline: '1',
    rel: '0',
    enablejsapi: '1',
    origin: window.location.origin,
  });
  return (
    <div className="discover-trailer">
      {!shown && (
        <p className="discover-note" role="status">
          Loading trailer…
        </p>
      )}
      <iframe
        ref={frame}
        className={shown ? 'discover-frame' : 'discover-frame discover-frame-hidden'}
        src={`${EMBED_ORIGIN}/embed/${video}?${params}`}
        title={`Trailer: ${title}`}
        allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
        // The page sends no Referer; YouTube's player needs this origin (and only this) to load.
        referrerPolicy="strict-origin-when-cross-origin"
      />
    </div>
  );
}
