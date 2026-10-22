import { type FormEvent, useEffect, useRef, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import type { AskTurn, Content, Session } from '../../api/types';

interface TitleChatProps {
  item: Content;
  session: Session;
  /** The title is one of the current picks, so "Why this pick?" has an answer. */
  picked: boolean;
}

interface Turn {
  question: string;
  answer: string;
  state: 'streaming' | 'done' | 'withdrawn' | 'failed';
  /** Seconds to the first words and to the whole answer. */
  first?: number;
  total?: number;
}

const seconds = (ms: number) => Math.round(ms / 100) / 10;
/** The time in milliseconds; read only in event handlers, never while rendering. */
const clock = () => performance.now();

/** Questions about one title, answered on this device by the local language model from Flicks' own facts. */
export function TitleChat({ item, session, picked }: TitleChatProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const controller = useRef<AbortController | null>(null);
  const busy = turns.at(-1)?.state === 'streaming';

  useEffect(() => () => controller.current?.abort(), []);

  const update = (change: Partial<Turn>) =>
    setTurns(current => current.map((turn, i) => (i === current.length - 1 ? { ...turn, ...change } : turn)));

  const ask = (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    const history: AskTurn[] = turns
      .filter(turn => turn.state === 'done')
      .map(({ question: q, answer }) => ({ question: q, answer }));
    setTurns(current => [...current, { question: text, answer: '', state: 'streaming' }]);
    setDraft('');
    controller.current = new AbortController();
    const start = clock();
    let first: number | undefined;
    flicksApi
      .askTitle(
        { id: item.id, question: text, session, history },
        event => {
          if ('delta' in event) {
            first ??= clock() - start;
            setTurns(current =>
              current.map((turn, i) =>
                i === current.length - 1 ? { ...turn, answer: turn.answer + event.delta } : turn,
              ),
            );
          } else if (event.ok) {
            update({
              answer: event.answer,
              state: 'done',
              first: seconds(first ?? 0),
              total: seconds(clock() - start),
            });
          } else {
            update({ answer: event.note, state: 'withdrawn', total: seconds(clock() - start) });
          }
        },
        controller.current.signal,
      )
      .catch((failure: unknown) => {
        if (controller.current?.signal.aborted) return;
        update({ answer: failure instanceof Error ? failure.message : 'The model could not answer.', state: 'failed' });
      });
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    ask(draft);
  };

  const suggestions = [
    'What is it about?',
    'Who is in it?',
    item.series ? 'How many seasons are there?' : 'Is it scary?',
    ...(picked ? ['Why this pick?'] : []),
  ];

  return (
    <section className="title-chat" aria-labelledby="title-chat-heading">
      <h3 id="title-chat-heading">Ask about {item.title}</h3>
      {turns.length > 0 && (
        <ol className="title-chat-turns">
          {turns.map((turn, index) => (
            <li key={index}>
              <p className="title-chat-question">{turn.question}</p>
              <p
                className={`title-chat-answer${turn.state === 'withdrawn' || turn.state === 'failed' ? ' title-chat-note' : ''}`}
                aria-live={index === turns.length - 1 ? 'polite' : undefined}
              >
                {turn.answer || (turn.state === 'streaming' ? 'Thinking…' : '')}
              </p>
              {turn.state === 'done' && (
                <p className="fine">
                  First words in {turn.first} s · answered in {turn.total} s · on this device
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
      <div className="chips chips-small" role="group" aria-label="Suggested questions">
        {suggestions.map(suggestion => (
          <button key={suggestion} type="button" className="chip" disabled={busy} onClick={() => ask(suggestion)}>
            {suggestion}
          </button>
        ))}
      </div>
      <form className="title-chat-form" onSubmit={submit}>
        <input
          value={draft}
          onChange={event => setDraft(event.target.value)}
          maxLength={300}
          placeholder="Ask anything about this title"
          aria-label={`Ask a question about ${item.title}`}
        />
        <button type="submit" className="button button-quiet" disabled={busy || !draft.trim()}>
          Ask
        </button>
      </form>
      <p className="fine">
        Answered by a small language model on this computer, from the details Flicks has. It can be wrong.
      </p>
    </section>
  );
}
