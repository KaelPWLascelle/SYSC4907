import { useEffect, useId, useRef, useState } from 'react';

import { DEFAULT_MIX, MOODS, type Mode, type Session } from '../../api/types';
import { RadioChips, ToggleChips } from '../../components/Chips';
import { cx } from '../../lib/cx';
import { capitalize, runtime, spokenTime } from '../../lib/format';
import { sameMix } from '../../lib/mix';
import { DEFAULT_SESSION } from '../session';

const MOOD_OPTIONS = MOODS.map(mood => ({ value: mood, label: mood === 'any' ? 'Anything' : capitalize(mood) }));
const MODE_OPTIONS = [
  { value: 'session', label: 'Taste + scene' },
  { value: 'baseline', label: 'Taste only' },
] as const;
const ENERGY = [
  { value: 0.2, label: 'Gentle' },
  { value: 0.5, label: 'Balanced' },
  { value: 0.9, label: 'Intense' },
] as const;
const TIME_PRESETS = [45, 90, 120, 180];

type Field = 'time' | 'mood' | 'energy';

interface SceneBarProps {
  session: Session;
  mode: Mode;
  genres: string[];
  onSession: (session: Session) => void;
  onMode: (mode: Mode) => void;
  /** Open "Your taste" to tune how picks are scored. */
  onTaste?: () => void;
}

const energyWord = (intensity: number) => (intensity < 0.35 ? 'gentle' : intensity > 0.65 ? 'intense' : 'balanced');

/**
 * The scene as one sentence ("I have 2 hours for something relaxing, gentle."): tap a word to
 * change it. Everything else (discovery, exact intensity, genres to avoid, the lens and the scoring mix)
 * waits behind "More", with a count of what has been changed there.
 */
export function SceneBar({ session, mode, genres, onSession, onMode, onTaste }: SceneBarProps) {
  const [field, setField] = useState<Field | null>(null);
  const [more, setMore] = useState(false);
  const pickerId = useId();
  const scene = useRef<HTMLElement>(null);
  const set = (patch: Partial<Session>) => onSession({ ...session, ...patch });

  // A picker stays open while you change it (arrow keys included) and closes on Escape or a click elsewhere.
  useEffect(() => {
    if (!field) return;
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setField(null);
    const onPointer = (event: PointerEvent) => {
      if (!scene.current?.contains(event.target as Node)) setField(null);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [field]);

  const advanced = [
    Math.abs(session.novelty - DEFAULT_SESSION.novelty) > 0.001,
    session.excluded_genres.length > 0,
    mode !== 'session',
    !sameMix(session.mix, DEFAULT_MIX),
    !ENERGY.some(e => Math.abs(e.value - session.intensity) < 0.001),
  ].filter(Boolean).length;
  const changed =
    advanced > 0 ||
    session.mood !== DEFAULT_SESSION.mood ||
    session.minutes !== DEFAULT_SESSION.minutes ||
    session.intensity !== DEFAULT_SESSION.intensity ||
    session.playable;

  const token = (name: Field, text: string, label: string) => (
    <button
      type="button"
      className={cx('scene-token', field === name && 'is-open')}
      aria-expanded={field === name}
      aria-controls={pickerId}
      aria-label={`${label}: ${text}. Change`}
      onClick={() => setField(field === name ? null : name)}
    >
      {text}
      <span className="scene-caret" aria-hidden="true" />
    </button>
  );

  return (
    <section className="scene" aria-label="Set the scene" ref={scene}>
      <p className="scene-sentence">
        I have {token('time', spokenTime(session.minutes), 'Time')} for something{' '}
        {/* Each word is glued to its punctuation, so a wrapped line never starts with a comma. */}
        <span className="nowrap">
          {token('mood', session.mood === 'any' ? 'any mood' : session.mood, 'Mood')},
        </span>{' '}
        <span className="nowrap">{token('energy', energyWord(session.intensity), 'Energy')}.</span>
      </p>

      {field && (
        <div className="scene-picker" id={pickerId}>
          {field === 'time' && <TimePicker minutes={session.minutes} onMinutes={minutes => set({ minutes })} />}
          {field === 'mood' && (
            <RadioChips label="Mood" options={MOOD_OPTIONS} value={session.mood} onChange={mood => set({ mood })} />
          )}
          {field === 'energy' && (
            <RadioChips
              label="Energy"
              options={ENERGY.map(e => ({ value: String(e.value), label: e.label }))}
              value={String(ENERGY.find(e => e.label.toLowerCase() === energyWord(session.intensity))?.value ?? 0.5)}
              onChange={value => set({ intensity: Number(value) })}
            />
          )}
        </div>
      )}

      <div className="scene-tools">
        <button
          type="button"
          className="chip"
          aria-pressed={session.playable}
          title="Only films you can press Play on now: your files and free streams"
          onClick={() => onSession({ ...session, playable: !session.playable })}
        >
          Ready to play
        </button>
        <button type="button" className="chip scene-more-toggle" aria-expanded={more} onClick={() => setMore(!more)}>
          {more ? 'Fewer options' : 'More options'}
          {advanced > 0 && <span className="scene-count">{advanced}</span>}
        </button>
        {changed && (
          <button
            type="button"
            className="link"
            onClick={() => {
              onSession({ ...DEFAULT_SESSION, mix: session.mix });
              onMode('session');
              setField(null);
            }}
          >
            Reset scene
          </button>
        )}
      </div>

      {more && (
        <div className="scene-more">
          <Slider
            id="intensity"
            label="Intensity"
            value={session.intensity}
            ends={['Easygoing', 'Full throttle']}
            onChange={intensity => onSession({ ...session, intensity })}
          />
          <Slider
            id="novelty"
            label="Discovery"
            value={session.novelty}
            ends={['Familiar', 'New territory']}
            onChange={novelty => onSession({ ...session, novelty })}
          />
          <div className="scene-group">
            <span className="scene-label">Ranking lens</span>
            <RadioChips
              label="Ranking lens"
              className="segmented"
              options={MODE_OPTIONS}
              value={mode}
              onChange={onMode}
            />
            {onTaste && (
              <button type="button" className="link" onClick={onTaste}>
                Tune how picks are scored
              </button>
            )}
          </div>
          <div className="scene-group scene-avoid">
            <span className="scene-label">
              Leave out {session.excluded_genres.length > 0 && `· ${session.excluded_genres.length}`}
            </span>
            <ToggleChips
              label="Genres to avoid"
              className="chips chips-small"
              options={genres.map(genre => ({ value: genre, label: capitalize(genre) }))}
              selected={session.excluded_genres}
              onChange={excluded_genres => onSession({ ...session, excluded_genres })}
            />
          </div>
        </div>
      )}
    </section>
  );
}

function TimePicker({ minutes, onMinutes }: { minutes: number; onMinutes: (minutes: number) => void }) {
  // The field keeps what the user typed; only valid minutes (1-600) reach the session.
  const [draft, setDraft] = useState<string | null>(null);
  const text = draft ?? String(minutes);
  const valid = /^\d+$/.test(text) && +text >= 1 && +text <= 600;
  return (
    <div className="scene-time">
      <div className="chips" role="group" aria-label="Time presets">
        {TIME_PRESETS.map(preset => (
          <button
            key={preset}
            type="button"
            className="chip"
            aria-pressed={minutes === preset}
            onClick={() => {
              setDraft(null);
              onMinutes(preset);
            }}
          >
            {runtime(preset)}
          </button>
        ))}
      </div>
      <label className="time">
        <span className="visually-hidden">Minutes</span>
        <input
          id="minutes"
          inputMode="numeric"
          value={text}
          aria-invalid={!valid}
          aria-describedby={valid ? undefined : 'minutes-error'}
          onChange={event => {
            const value = event.target.value.trim();
            setDraft(value);
            if (/^\d+$/.test(value) && +value >= 1 && +value <= 600) onMinutes(+value);
          }}
          onBlur={() => setDraft(null)}
        />
        <span>min</span>
      </label>
      {!valid && (
        <span className="field-error" id="minutes-error">
          1 to 600 minutes
        </span>
      )}
    </div>
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
