import { type Ref, useSyncExternalStore } from 'react';

import type { VoiceStatus } from '../../api/types';
import type { CommandController } from '../commands/CommandController';

interface AskBarProps {
  controller: CommandController;
  voice: VoiceStatus;
  inputRef?: Ref<HTMLTextAreaElement>;
}

/** Typed or spoken requests, always previewed before anything changes. */
export function AskBar({ controller, voice, inputRef }: AskBarProps) {
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const idle = state.phase === 'idle';
  const recording = state.phase === 'recording';
  const cancellable = ['requesting', 'recording', 'transcribing'].includes(state.phase);

  return (
    <section className="ask" aria-labelledby="ask-heading">
      <h2 id="ask-heading" className="visually-hidden">
        Ask Flicks
      </h2>
      {voice.available && (
        <div className="ask-head">
          <span className="badge">Whisper · on device</span>
          <p className="hint" role="status" aria-live="polite">
            {state.voiceStatus}
          </p>
        </div>
      )}
      <form
        className="ask-bar"
        onSubmit={event => {
          event.preventDefault();
          void controller.preview();
        }}
      >
        {voice.available && (
          <button
            type="button"
            className="mic"
            aria-pressed={recording}
            disabled={!controller.canRecord || !(idle || recording)}
            onClick={() => void controller.toggleRecord()}
          >
            <span aria-hidden="true">{recording ? '■' : '●'}</span>
            <span className="mic-label">{recording ? 'Stop & transcribe' : 'Record command'}</span>
          </button>
        )}
        <label htmlFor="command-text" className="visually-hidden">
          Ask Flicks, or edit the transcript
        </label>
        <textarea
          id="command-text"
          ref={inputRef}
          rows={1}
          maxLength={500}
          placeholder="Ask for anything: funny films from the 90s, play The General, no horror…"
          value={state.text}
          disabled={!idle}
          onChange={event => controller.setText(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <button type="submit" className="button button-quiet" disabled={!idle}>
          Preview
        </button>
        <button
          type="button"
          className="button button-primary"
          disabled={!idle || !state.canApply}
          onClick={() => void controller.apply()}
        >
          Apply
        </button>
      </form>
      <div className="ask-foot">
        <p className="ask-message" role="status" aria-live="polite">
          {state.message}
        </p>
        <div className="ask-tools">
          {cancellable && (
            <button type="button" className="link" onClick={() => controller.cancel()}>
              Cancel
            </button>
          )}
          {voice.available && (
            <label className="link file-pick">
              Use a recording
              <input
                type="file"
                accept="audio/*"
                disabled={!idle}
                onChange={event => {
                  const file = event.target.files?.[0];
                  if (file) controller.transcribeFile(file);
                  event.target.value = '';
                }}
              />
            </label>
          )}
        </div>
      </div>
      {voice.available && (
        <p className="fine">
          The microphone starts only when you press record. Up to 30 seconds, transcribed on this device, never saved.
          No wake word.
        </p>
      )}
    </section>
  );
}
