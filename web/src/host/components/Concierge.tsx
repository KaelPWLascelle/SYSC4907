import { type FormEvent, useEffect, useRef, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import type { ConciergeMessage, Content, Recommendation, Session } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Poster } from '../../components/Poster';
import { subtitle } from '../../lib/format';
import { useLibrary } from '../library';
import { reasons } from '../reasons';

interface ConciergeProps {
  session: Session;
  /** Open a pick's details sheet. */
  onOpen: (item: Content) => void;
  /** Make the settings the conversation arrived at the scene on Home. */
  onApply: (session: Session) => void;
}

interface Line extends ConciergeMessage {
  /** user lines: the chips for what Flicks understood from everything said so far. */
  understood?: string[];
  /** assistant lines */
  picks?: Recommendation[];
  scene?: Session;
  streaming?: boolean;
}

const GREETING: Line = { role: 'assistant', text: 'Hi! What are you in the mood for tonight?' };
const STARTERS = ['Cozy and funny', 'Edge of my seat', 'Something thoughtful', 'Surprise me'];
const AFTER_PICKS = ['Show me others', 'Under 90 minutes', 'Something lighter'];

/** The corner chat: a few questions, then three picks for tonight. Works without a language model. */
export function Concierge({ session, onOpen, onApply }: ConciergeProps) {
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<Line[]>([GREETING]);
  const [draft, setDraft] = useState('');
  const [shown, setShown] = useState<string[]>([]);
  const library = useLibrary();
  const controller = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const busy = lines.at(-1)?.streaming ?? false;
  const last = lines.at(-1);

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' });
  }, [lines]);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !document.querySelector('dialog[open]')) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  const patchLast = (change: (line: Line) => Line) =>
    setLines(current => current.map((line, i) => (i === current.length - 1 ? change(line) : line)));

  const send = (text: string) => {
    const words = text.trim();
    if (!words || busy) return;
    const conversation = [...lines, { role: 'user' as const, text: words }];
    setLines([...conversation, { role: 'assistant', text: '', streaming: true }]);
    setDraft('');
    controller.current = new AbortController();
    flicksApi
      .concierge(
        { messages: conversation.map(({ role, text: said }) => ({ role, text: said })), session, shown },
        event => {
          if ('understood' in event) {
            setLines(current =>
              current.map((line, i) => (i === current.length - 2 ? { ...line, understood: event.understood } : line)),
            );
          } else if ('picks' in event) {
            setShown(current => [...current, ...event.picks.map(pick => pick.content.id)]);
            patchLast(line => ({ ...line, picks: event.picks, scene: event.session }));
          } else if ('delta' in event) {
            patchLast(line => ({ ...line, text: line.text + event.delta }));
          } else {
            patchLast(line => ({ ...line, text: event.text, streaming: false }));
          }
        },
        controller.current.signal,
      )
      .catch((failure: unknown) => {
        if (controller.current?.signal.aborted) return;
        patchLast(line => ({
          ...line,
          text: failure instanceof Error ? failure.message : 'Something went wrong. Try again.',
          streaming: false,
        }));
      });
  };

  const restart = () => {
    controller.current?.abort();
    setLines([GREETING]);
    setShown([]);
    input.current?.focus();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    send(draft);
  };

  const replies = busy ? [] : lines.length === 1 ? STARTERS : last?.picks ? AFTER_PICKS : [];

  return (
    <>
      <button
        type="button"
        className={`concierge-fab${open ? ' concierge-fab-open' : ''}`}
        aria-label={open ? 'Close Flicks chat' : 'Chat with Flicks to find something to watch'}
        aria-expanded={open}
        aria-controls="concierge"
        onClick={() => setOpen(value => !value)}
      >
        <Icon name={open ? 'close' : 'sparkle'} />
      </button>
      {open && (
        <section id="concierge" className="concierge" role="dialog" aria-label="Flicks chat">
          <header className="concierge-head">
            <span className="concierge-avatar" aria-hidden="true">
              <Icon name="sparkle" />
            </span>
            <div>
              <h2>Flicks</h2>
              <p>Finds something for tonight · on this device</p>
            </div>
            {lines.length > 1 && (
              <button type="button" className="concierge-restart" onClick={restart}>
                Start over
              </button>
            )}
          </header>
          <div className="concierge-body">
            {lines.map((line, index) =>
              line.role === 'user' ? (
                <div key={index} className="concierge-user">
                  <p>{line.text}</p>
                  {line.understood && line.understood.length > 0 && (
                    <ul className="concierge-understood" aria-label="What Flicks understood">
                      {line.understood.map(label => (
                        <li key={label}>{label}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : (
                <div
                  key={index}
                  className="concierge-assistant"
                  aria-live={index === lines.length - 1 ? 'polite' : undefined}
                >
                  {line.text ? (
                    <p>{line.text}</p>
                  ) : (
                    <span className="title-chat-typing" role="status" aria-label="Thinking">
                      <span />
                      <span />
                      <span />
                    </span>
                  )}
                  {line.picks && (
                    <>
                      <ul className="concierge-picks" aria-label="Picks for tonight">
                        {line.picks.map(pick => (
                          <li key={pick.content.id}>
                            <button type="button" className="concierge-pick" onClick={() => onOpen(pick.content)}>
                              <Poster
                                item={pick.content}
                                hasPoster={library.posters.has(pick.content.id)}
                                className="poster concierge-poster"
                              />
                              <span className="concierge-pick-text">
                                <strong>{pick.content.title}</strong>
                                <span>{subtitle(pick.content)}</span>
                                <span className="concierge-reason">{reasons(pick, line.scene ?? session)[0]}</span>
                              </span>
                              {library.media.has(pick.content.id) && <span className="concierge-ready">Ready</span>}
                            </button>
                          </li>
                        ))}
                      </ul>
                      {line.scene && !line.streaming && (
                        <button
                          type="button"
                          className="concierge-apply"
                          onClick={() => line.scene && onApply(line.scene)}
                        >
                          Use these settings on Home
                        </button>
                      )}
                    </>
                  )}
                </div>
              ),
            )}
            <div ref={end} />
          </div>
          {replies.length > 0 && (
            <div className="concierge-replies" role="group" aria-label="Quick replies">
              {replies.map(reply => (
                <button key={reply} type="button" className="chip" onClick={() => send(reply)}>
                  {reply}
                </button>
              ))}
            </div>
          )}
          <form className="title-chat-form concierge-form" onSubmit={submit}>
            <input
              ref={input}
              value={draft}
              onChange={event => setDraft(event.target.value)}
              maxLength={300}
              placeholder="Tell Flicks what you feel like"
              aria-label="Message Flicks"
            />
            <button type="submit" className="title-chat-send" aria-label="Send" disabled={busy || !draft.trim()}>
              <Icon name="arrowUp" />
            </button>
          </form>
        </section>
      )}
    </>
  );
}
