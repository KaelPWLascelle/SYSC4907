import type { CSSProperties } from 'react';

import type { CouchHostView, CouchProgress, CouchResult, Session } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { cx } from '../../lib/cx';
import type { useCouchHost } from '../hooks/useCouchHost';

const PLAYER_LABELS = { playing: 'Playing', paused: 'Paused', stopped: 'Stopped' } as const;
/** One flat colour per guest, like seats picked out on a sofa (the same set as profile avatars). */
const GUEST_COLOURS = ['#ffb4a2', '#9bd4c8', '#b9b4ff', '#ffe2a8'];
/** The sofa always has room for a few more. */
const MIN_SEATS = 4;

interface CouchPanelProps {
  couch: ReturnType<typeof useCouchHost>;
  session: Session;
}

type Live = Extract<CouchHostView, { active: true }>;

/**
 * The TV side of couch mode, drawn as the room: a code to scan, the shortlist on screen, and a sofa that
 * fills as phones join, with a bulb over each seat that lights when that person has finished voting.
 * At the reveal the other titles step back and the spotlight finds the group's pick.
 */
export function CouchPanel({ couch, session }: CouchPanelProps) {
  const { view, busy, error } = couch;
  return (
    <section id="couch" className="couch-panel" aria-labelledby="couch-heading">
      {!view.active ? (
        <div className="couch-idle">
          <div>
            <h2 id="couch-heading">Picking with friends?</h2>
            <p>
              Everyone on this Wi-Fi scans a code, swipes through a shortlist built from your scene, and the group’s
              pick lands here. Guests never see your ratings or history.
            </p>
          </div>
          <button type="button" className="button button-quiet" disabled={busy} onClick={() => couch.start(session)}>
            Start a couch session
          </button>
        </div>
      ) : (
        <LiveCouch couch={couch} view={view} />
      )}
      {error && (
        <p className="notice" role="status">
          {error}
        </p>
      )}
    </section>
  );
}

function LiveCouch({ couch, view }: { couch: CouchPanelProps['couch']; view: Live }) {
  const { busy } = couch;
  const results = view.results ?? [];
  const result = (id: string) => results.find(row => row.id === id);
  const winner = view.revealed ? results[0] : undefined;
  const winnerItem = winner && view.items.find(item => item.id === winner.id);
  const title = (id: string) => view.items.find(item => item.id === id)?.title ?? id;
  const done = view.progress.filter(p => p.total > 0 && p.voted >= p.total).length;
  const status = view.revealed
    ? 'Picked. Press Play on the group’s pick, or on anything else in the shortlist.'
    : !view.progress.length
      ? 'Waiting for the first phone.'
      : done === view.progress.length
        ? 'Everyone has voted.'
        : `${view.progress.length} on the couch, ${done} finished voting.`;

  return (
    <div className={cx('couch-live', winner && 'is-revealed')}>
      <div className="couch-join">
        <h2 id="couch-heading">Couch vote</h2>
        <p className="hint">Scan with a phone on this Wi-Fi. No app, no account.</p>
        <img
          src={`/api/couch/qr.svg?code=${encodeURIComponent(view.code)}`}
          alt="QR code to join this couch session"
          width={200}
          height={200}
        />
        <p className="hint">
          Or open <strong>{view.url}</strong> and enter
        </p>
        <p className="couch-code">{view.code}</p>
        <p className="couch-status" role="status">
          {status}
        </p>
        <div className="remote-buttons">
          <button
            type="button"
            className="button button-primary"
            disabled={busy || view.revealed || !view.progress.length}
            onClick={() => couch.reveal()}
          >
            Reveal results now
          </button>
          <button type="button" className="button button-quiet" disabled={busy} onClick={() => couch.stop()}>
            End session
          </button>
        </div>
      </div>

      <div className="couch-stage">
        {view.items.length > 0 && (
          <ul
            className="couch-shortlist"
            aria-label="Shortlist"
            style={
              {
                '--cols': view.items.length <= 5 ? view.items.length : Math.ceil(view.items.length / 2),
              } as CSSProperties
            }
          >
            {view.items.map((item, index) => {
              const row = result(item.id);
              return (
                <li
                  key={item.id}
                  className={cx('couch-film', winner?.id === item.id && 'is-winner')}
                  style={{ '--n': index } as CSSProperties}
                >
                  <div className="beam" aria-hidden="true" />
                  <Poster item={item} hasPoster={item.poster} />
                  {row && <Votes row={row} title={item.title} />}
                  {row && (
                    <button
                      type="button"
                      className="button button-quiet couch-play"
                      aria-label={`Play ${item.title}`}
                      disabled={busy}
                      onClick={() => couch.player('select', item.id)}
                    >
                      <Icon name="play" />
                      Play
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {winner && winnerItem && (
          <p className="couch-verdict" role="status">
            Tonight it’s {winnerItem.title}, with {winner.yes} of {winner.yes + winner.no} yes votes
            {winner.match ? '. It’s a match: everyone said yes.' : '.'}
          </p>
        )}
        <Sofa progress={view.progress} />
        <p className="hint couch-now">
          {view.player.id
            ? `${PLAYER_LABELS[view.player.state]}: ${title(view.player.id)}${view.player.by ? `, from ${view.player.by}` : ''}`
            : 'Nothing playing yet.'}
        </p>
      </div>
    </div>
  );
}

/** A title's votes as bulbs: one lit for each yes, an outline for each no. */
function Votes({ row, title }: { row: CouchResult; title: string }) {
  return (
    <span className="bulbs" role="img" aria-label={`${title}: ${row.yes} yes, ${row.no} no`}>
      {Array.from({ length: row.yes }, (_, k) => (
        <i key={`y${k}`} className="bulb on" style={{ '--i': k } as CSSProperties} />
      ))}
      {Array.from({ length: row.no }, (_, k) => (
        <i key={`n${k}`} className="bulb seen" />
      ))}
    </span>
  );
}

/** The sofa: a seat per guest, plus empty ones. A guest's bulb lights once they have voted on everything. */
function Sofa({ progress }: { progress: CouchProgress[] }) {
  const empty = Math.max(0, MIN_SEATS - progress.length);
  return (
    <div className="sofa">
      <span className="sofa-arm" aria-hidden="true" />
      <ul className="seats" aria-label="Who’s voting">
        {progress.map((p, index) => {
          const finished = p.total > 0 && p.voted >= p.total;
          return (
            <li
              key={p.name}
              className={cx('seat', finished ? 'is-done' : p.voted > 0 && 'is-voting')}
              style={{ '--g': GUEST_COLOURS[index % GUEST_COLOURS.length] } as CSSProperties}
            >
              <span className="seat-bulb" aria-hidden="true" />
              <span className="seat-person" aria-hidden="true">
                {p.name.slice(0, 1).toUpperCase()}
              </span>
              <span className="seat-cushion" aria-hidden="true" />
              <span className="visually-hidden">{`${p.name}: ${p.voted} of ${p.total}`}</span>
              <span className="seat-label" aria-hidden="true">
                <b>{p.name}</b>
                <small>
                  {p.voted} of {p.total}
                </small>
              </span>
            </li>
          );
        })}
        {Array.from({ length: empty }, (_, k) => (
          <li key={`empty${k}`} className="seat is-empty" aria-hidden="true">
            <span className="seat-bulb" />
            <span className="seat-cushion" />
          </li>
        ))}
      </ul>
      <span className="sofa-arm" aria-hidden="true" />
    </div>
  );
}
