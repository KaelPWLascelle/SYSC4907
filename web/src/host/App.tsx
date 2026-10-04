import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { flicksApi } from '../api/flicks';
import type { AppState, Mode, Rating } from '../api/types';
import { CommandController } from './commands/CommandController';
import { AskBar } from './components/AskBar';
import { Browse } from './components/Browse';
import { CouchPanel } from './components/CouchPanel';
import { DetailsSheet } from './components/DetailsSheet';
import { Hero } from './components/Hero';
import { Player } from './components/Player';
import { Rail } from './components/Rail';
import { SceneBar } from './components/SceneBar';
import { Tile } from './components/Tile';
import { Footer, TopBar } from './components/TopBar';
import { useCouchHost } from './hooks/useCouchHost';
import { useHistory } from './hooks/useHistory';
import { useRecommendations } from './hooks/useRecommendations';
import { type Library, LibraryContext } from './library';
import { DEFAULT_SESSION } from './session';

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

export function App() {
  const [data, setData] = useState<AppState | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    flicksApi.state().then(setData, failure => setError(message(failure)));
  }, []);
  if (!data) {
    return (
      <main className="loading" aria-busy={!error}>
        <p role="status">{error ? `Could not load Flicks: ${error}. Reload to retry.` : 'Loading Flicks…'}</p>
      </main>
    );
  }
  return <Home initial={data} />;
}

function Home({ initial }: { initial: AppState }) {
  const [feedback, setFeedback] = useState(initial.feedback);
  const [session, setSession] = useState(DEFAULT_SESSION);
  const [mode, setMode] = useState<Mode>('session');
  const [detailsId, setDetailsId] = useState<string | null>(null);
  const [playing, setPlaying] = useState<{ id: string; startAt: number } | null>(null);
  const [ratingBusy, setRatingBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const askInput = useRef<HTMLTextAreaElement>(null);

  const recommendations = useRecommendations(session, mode, feedback);
  const history = useHistory();
  const couch = useCouchHost(initial.couch);

  const byId = useMemo(() => new Map(initial.catalog.map(item => [item.id, item])), [initial.catalog]);
  const posters = useMemo(() => new Set(initial.posters), [initial.posters]);
  const media = useMemo(() => new Map(initial.media.map(entry => [entry.id, entry])), [initial.media]);
  const progress = useMemo(() => new Map(history.items.map(p => [p.content_id, p])), [history.items]);
  const genres = useMemo(() => [...new Set(initial.catalog.flatMap(item => item.genres))].sort(), [initial.catalog]);

  // ---------- assistant ----------
  const [controller] = useState(
    () =>
      new CommandController({
        voice: initial.voice,
        session: DEFAULT_SESSION,
        preview: flicksApi.previewCommand,
        apply: flicksApi.applyCommand,
        transcribe: flicksApi.transcribe,
        onApplied: result => {
          setFeedback(result.feedback);
          setSession(result.session);
        },
      }),
  );
  useEffect(() => controller.setSession(session), [controller, session]);
  useEffect(() => {
    const dispose = () => controller.dispose();
    window.addEventListener('pagehide', dispose);
    return () => window.removeEventListener('pagehide', dispose);
  }, [controller]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (event.key === '/' && !target.closest('input, textarea, select, [contenteditable], dialog')) {
        event.preventDefault();
        askInput.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  // ---------- ratings and playback ----------
  const ratingBusyRef = useRef(false);
  const rate = useCallback(async (id: string, value: Rating | 0) => {
    if (ratingBusyRef.current) return;
    ratingBusyRef.current = true;
    setRatingBusy(true);
    try {
      setFeedback((await flicksApi.rate(id, value)).feedback);
      setNotice('');
    } catch (failure) {
      setNotice(`Could not save your rating: ${message(failure)}`);
    } finally {
      ratingBusyRef.current = false;
      setRatingBusy(false);
    }
  }, []);

  const play = useCallback(
    (id: string, fromStart = false) => {
      const saved = progress.get(id);
      setDetailsId(null);
      setPlaying({ id, startAt: !fromStart && saved?.resumable ? saved.position_seconds : 0 });
    },
    [progress],
  );

  const library = useMemo<Library>(
    () => ({ byId, posters, media, feedback, progress, ratingBusy, rate, openDetails: setDetailsId, play }),
    [byId, posters, media, feedback, progress, ratingBusy, rate, play],
  );

  // ---------- couch remote -> player ----------
  // Each distinct remote command (title + state) is applied once; `remoteVersion` tells the player.
  const couchPlayer = couch.view.active ? couch.view.player : null;
  const remoteKey = couchPlayer?.id ? `${couchPlayer.id}:${couchPlayer.state}` : null;
  const [remote, setRemote] = useState<{ key: string | null; version: number }>({ key: null, version: 0 });
  if (remoteKey !== remote.key) {
    // Adjusting state while rendering (not in an effect): runs exactly once per new remote command.
    setRemote({ key: remoteKey, version: remote.version + 1 });
    const id = couchPlayer?.id;
    if (id && couchPlayer.state === 'playing' && media.has(id) && playing?.id !== id) {
      const saved = progress.get(id);
      setDetailsId(null);
      setPlaying({ id, startAt: saved?.resumable ? saved.position_seconds : 0 });
    }
  }

  const remoteForPlayer =
    playing && couchPlayer?.id === playing.id ? { state: couchPlayer.state, version: remote.version } : null;
  const reportPlayback = (state: 'playing' | 'paused') => {
    if (couchPlayer?.id && couchPlayer.id === playing?.id && couchPlayer.state !== state) {
      void couch.player(state === 'playing' ? 'play' : 'pause');
    }
  };
  const closePlayer = () => {
    if (couchPlayer?.id && couchPlayer.id === playing?.id && couchPlayer.state !== 'stopped') void couch.player('stop');
    setPlaying(null);
    void history.refresh();
  };

  // ---------- render ----------
  const continueWatching = history.items.flatMap(p => {
    const item = byId.get(p.content_id);
    return p.resumable && item && media.has(item.id) ? [item] : [];
  });
  const { picks, coldStart, loading, error } = recommendations;
  const status = error
    ? `Could not load picks: ${error}`
    : !picks.length && !loading
      ? 'Nothing fits yet. Add time, drop an avoided genre, or clear a rating.'
      : coldStart
        ? 'Like a few films below and Flicks learns your taste. Until then, picks follow your scene.'
        : 'Shaped by your ratings and this scene. Open any title to see why it ranks where it does.';
  const playingItem = playing ? byId.get(playing.id) : undefined;

  return (
    <LibraryContext.Provider value={library}>
      <a className="skip-link" href="#picks">
        Skip to your picks
      </a>
      <TopBar couch={initial.couch} onAsk={() => askInput.current?.focus()} />
      <main id="top">
        <Hero pick={picks[0]} session={session} mode={mode} loading={loading && !picks.length} />
        <AskBar controller={controller} voice={initial.voice} inputRef={askInput} />
        <SceneBar session={session} mode={mode} genres={genres} onSession={setSession} onMode={setMode} />
        {notice && (
          <p className="notice page-notice" role="alert">
            {notice}
          </p>
        )}
        {continueWatching.length > 0 && (
          <Rail id="continue" title="Continue watching">
            {continueWatching.map(item => (
              <Tile key={item.id} item={item} resume />
            ))}
          </Rail>
        )}
        <Rail
          id="picks"
          title="Top picks for this moment"
          status={status}
          badge={picks.length ? `${picks.length} picks` : undefined}
        >
          {picks.map((row, index) => (
            <Tile key={row.content.id} item={row.content} rank={index + 1} />
          ))}
        </Rail>
        {initial.couch && <CouchPanel couch={couch} session={session} />}
        <Browse catalog={initial.catalog} />
      </main>
      <Footer titles={initial.catalog.length} posters={posters.size > 0} playable={media.size} />
      <DetailsSheet id={detailsId} picks={picks} session={session} onClose={() => setDetailsId(null)} />
      {playing && playingItem && (
        <Player
          key={playing.id}
          item={playingItem}
          startAt={playing.startAt}
          directPlay={media.get(playing.id)?.direct_play ?? true}
          remote={remoteForPlayer}
          onProgress={(position, duration) => {
            flicksApi.saveProgress(playing.id, position, duration).catch(() => {
              // Progress is best effort; the next save retries.
            });
          }}
          onPlayback={reportPlayback}
          onClose={closePlayer}
        />
      )}
    </LibraryContext.Provider>
  );
}
