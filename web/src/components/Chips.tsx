import { type KeyboardEvent, useRef } from 'react';

interface Option<T extends string> {
  value: T;
  label: string;
}

interface RadioChipsProps<T extends string> {
  label: string;
  options: readonly Option<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/** A single-choice group with radio semantics and roving focus (arrow keys move and select). */
export function RadioChips<T extends string>({
  label,
  options,
  value,
  onChange,
  className = 'chips',
}: RadioChipsProps<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = (index + step + options.length) % options.length;
    const option = options[next];
    if (!option) return;
    onChange(option.value);
    refs.current[next]?.focus();
  };
  return (
    <div className={className} role="radiogroup" aria-label={label}>
      {options.map((option, index) => (
        <button
          key={option.value}
          ref={node => {
            refs.current[index] = node;
          }}
          type="button"
          role="radio"
          className="chip"
          aria-checked={option.value === value}
          tabIndex={option.value === value ? 0 : -1}
          onClick={() => onChange(option.value)}
          onKeyDown={event => onKeyDown(event, index)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

interface ToggleChipsProps {
  label: string;
  options: readonly Option<string>[];
  selected: readonly string[];
  onChange: (selected: string[]) => void;
  className?: string;
}

/** A multi-select group of toggle buttons. */
export function ToggleChips({ label, options, selected, onChange, className = 'chips' }: ToggleChipsProps) {
  return (
    <div className={className} role="group" aria-label={label}>
      {options.map(option => {
        const on = selected.includes(option.value);
        return (
          <button
            key={option.value}
            type="button"
            className="chip"
            aria-pressed={on}
            onClick={() => onChange(on ? selected.filter(v => v !== option.value) : [...selected, option.value])}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
