import { useState } from 'react';

import { cx } from '../../lib/cx';

import { type Medium, MOODS, type Mode, type Session } from '../../api/types';
import { RadioChips, ToggleChips } from '../../components/Chips';
import { capitalize, runtime } from '../../lib/format';

const MOOD_OPTIONS = MOODS.map(mood => ({ value: mood, label: mood === 'any' ? 'Anything' : capitalize(mood) }));
const MODE_OPTIONS = [
  { value: 'session', label: 'Taste + scene' },
  { value: 'baseline', label: 'Taste only' },
] as const;
const MEDIUM_OPTIONS: { value: Medium; label: string }[] = [
  { value: 'any', label: 'Either' },
  { value: 'watch', label: 'Watch' },
  { value: 'listen', label: 'Listen' },
];
const TIME_PRESETS = [45, 90, 120, 180];

interface SceneBarProps {
  session: Session;
  mode: Mode;
  genres: string[];
  /** Offer watch / listen when a podcast catalogue is loaded. */
  podcasts?: boolean;
  onSession: (session: Session) => void;
  onMode: (mode: Mode) => void;
}

/** The scene: mood, time, intensity, discovery, genres to avoid, and the ranking lens. */
const PHONE = '(max-width: 720px)';

/** One line describing the scene, shown on phones where the full controls start folded away. */
function summary(session: Session, podcasts: boolean) {
  const parts = [
    ...(podcasts ? [MEDIUM_OPTIONS.find(o => o.value === session.medium)?.label ?? 'Either'] : []),
    session.mood === 'any' ? 'Any mood' : capitalize(session.mood),
    runtime(session.minutes),
    `intensity ${Math.round(session.intensity * 100)}%`,
  ];
  if (session.excluded_genres.length) parts.push(`avoiding ${session.excluded_genres.length}`);
  return parts.join(' · ');
}

export function SceneBar({ session, mode, genres, podcasts = false, onSession, onMode }: SceneBarProps) {
  const [open, setOpen] = useState(() => !globalThis.matchMedia?.(PHONE).matches);
  // The field keeps what the user typed; only valid minutes (1-600) reach the session.
  const [minutesDraft, setMinutesDraft] = useState<string | null>(null);
  const minutesText = minutesDraft ?? String(session.minutes);
  const minutesValid = /^\d+$/.test(minutesText) && +minutesText >= 1 && +minutesText <= 600;
  const set = (patch: Partial<Session>) => onSession({ ...session, ...patch });

  return (
    <section className={cx('scene', !open && 'scene-folded')} aria-label="Set the scene">
      <button type="button" className="scene-toggle" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        <span className="scene-label">Scene</span>
        <span className="scene-summary">{summary(session, podcasts)}</span>
        <span className="link">{open ? 'Done' : 'Adjust'}</span>
      </button>
      {podcasts && (
        <div className="scene-group">
          <span className="scene-label">Watch or listen</span>
          <RadioChips
            label="Watch or listen"
            className="segmented"
            options={MEDIUM_OPTIONS}
            value={session.medium}
            onChange={medium => set({ medium })}
          />
        </div>
      )}
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
