import { useState } from 'react';

import { MOODS, type Mode, type Session } from '../../api/types';
import { RadioChips, ToggleChips } from '../../components/Chips';
import { capitalize, runtime } from '../../lib/format';

const MOOD_OPTIONS = MOODS.map(mood => ({ value: mood, label: mood === 'any' ? 'Anything' : capitalize(mood) }));
const MODE_OPTIONS = [
  { value: 'session', label: 'Taste + scene' },
  { value: 'baseline', label: 'Taste only' },
] as const;
const TIME_PRESETS = [45, 90, 120, 180];

interface SceneBarProps {
  session: Session;
  mode: Mode;
  genres: string[];
  onSession: (session: Session) => void;
  onMode: (mode: Mode) => void;
}

/** The scene: mood, time, intensity, discovery, genres to avoid, and the ranking lens. */
export function SceneBar({ session, mode, genres, onSession, onMode }: SceneBarProps) {
  // The field keeps what the user typed; only valid minutes (1-600) reach the session.
  const [minutesDraft, setMinutesDraft] = useState<string | null>(null);
  const minutesText = minutesDraft ?? String(session.minutes);
  const minutesValid = /^\d+$/.test(minutesText) && +minutesText >= 1 && +minutesText <= 600;
  const set = (patch: Partial<Session>) => onSession({ ...session, ...patch });

  return (
    <section className="scene" aria-label="Set the scene">
      <div className="scene-group">
        <span className="scene-label" id="mood-label">
          Mood
        </span>
        <RadioChips label="Mood" options={MOOD_OPTIONS} value={session.mood} onChange={mood => set({ mood })} />
      </div>
      <div className="scene-group">
        <label className="scene-label" htmlFor="minutes">
          Time
        </label>
        <div className="time">
          <input
            id="minutes"
            inputMode="numeric"
            value={minutesText}
            aria-invalid={!minutesValid}
            aria-describedby={minutesValid ? undefined : 'minutes-error'}
            onChange={event => {
              const text = event.target.value.trim();
              setMinutesDraft(text);
              if (/^\d+$/.test(text) && +text >= 1 && +text <= 600) set({ minutes: +text });
            }}
            onBlur={() => setMinutesDraft(null)}
          />
          <span>min</span>
        </div>
        {!minutesValid && (
          <span className="field-error" id="minutes-error">
            1 to 600 minutes
          </span>
        )}
        <div className="chips chips-small" role="group" aria-label="Time presets">
          {TIME_PRESETS.map(minutes => (
            <button
              key={minutes}
              type="button"
              className="chip"
              aria-pressed={session.minutes === minutes}
              onClick={() => {
                setMinutesDraft(null);
                set({ minutes });
              }}
            >
              {runtime(minutes)}
            </button>
          ))}
        </div>
      </div>
      <Slider
        id="intensity"
        label="Intensity"
        value={session.intensity}
        ends={['Easygoing', 'Full throttle']}
        onChange={intensity => set({ intensity })}
      />
      <Slider
        id="novelty"
        label="Discovery"
        value={session.novelty}
        ends={['Familiar', 'New territory']}
        onChange={novelty => set({ novelty })}
      />
      <details className="scene-group scene-avoid">
        <summary className="scene-label">
          Avoid {session.excluded_genres.length > 0 && `· ${session.excluded_genres.length}`}
        </summary>
        <ToggleChips
          label="Genres to avoid"
          className="chips chips-small"
          options={genres.map(genre => ({ value: genre, label: capitalize(genre) }))}
          selected={session.excluded_genres}
          onChange={excluded_genres => set({ excluded_genres })}
        />
      </details>
      <div className="scene-group">
        <span className="scene-label">Lens</span>
        <RadioChips label="Ranking lens" className="segmented" options={MODE_OPTIONS} value={mode} onChange={onMode} />
      </div>
    </section>
  );
}

interface SliderProps {
  id: string;
  label: string;
  value: number;
  ends: [string, string];
  onChange: (value: number) => void;
}

function Slider({ id, label, value, ends, onChange }: SliderProps) {
  const percent = Math.round(value * 100);
  return (
    <div className="scene-group scene-slider">
      <label className="scene-label" htmlFor={id}>
        {label} <output htmlFor={id}>{percent}%</output>
      </label>
      <input
        id={id}
        type="range"
        min={0}
        max={100}
        value={percent}
        onChange={event => onChange(Number(event.target.value) / 100)}
      />
      <div className="ends" aria-hidden="true">
        <span>{ends[0]}</span>
        <span>{ends[1]}</span>
      </div>
    </div>
  );
}
