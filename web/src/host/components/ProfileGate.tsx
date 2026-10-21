import { useEffect, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import type { ProfilesResponse, ProfileSummary } from '../../api/types';
import { Logo } from '../../components/Logo';

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const PIN = /^\d{4,8}$/;

/** "Who's watching?": choose a profile (with its PIN if it has one) or add one. Profiles stay on this device. */
export function ProfileGate({ onReady }: { onReady: () => void }) {
  const [listing, setListing] = useState<ProfilesResponse | null>(null);
  const [error, setError] = useState('');
  const [locked, setLocked] = useState<ProfileSummary | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    flicksApi.profiles.list().then(setListing, failure => setError(message(failure)));
  }, []);

  const choose = async (profile: ProfileSummary, pin: string | null = null) => {
    if (profile.locked && pin === null) {
      setError('');
      setLocked(profile);
      return;
    }
    try {
      await flicksApi.profiles.select(profile.id, pin);
      onReady();
    } catch (failure) {
      setError(message(failure));
    }
  };

  return (
    <main className="gate" aria-labelledby="gate-title">
      <div className="gate-logo">
        <Logo />
      </div>
      <h1 id="gate-title">Who’s watching?</h1>
      <p className="fine">
        Each profile keeps its own ratings, history and picks. They are stored only on this device.
      </p>
      {!listing && !error && <p role="status">Loading profiles…</p>}
      {listing && !locked && !adding && (
        <ul className="gate-profiles" aria-label="Profiles">
          {listing.profiles.map(profile => (
            <li key={profile.id}>
              <button type="button" className="gate-profile" onClick={() => void choose(profile)}>
                <span className="avatar" aria-hidden="true">
                  {profile.name.slice(0, 1).toUpperCase()}
                </span>
                <span className="gate-name">{profile.name}</span>
                <span className="fine">
                  {profile.locked ? 'PIN · ' : ''}
                  {profile.ratings} {profile.ratings === 1 ? 'rating' : 'ratings'}
                </span>
              </button>
            </li>
          ))}
          <li>
            <button type="button" className="gate-profile gate-add" onClick={() => setAdding(true)}>
              <span className="avatar" aria-hidden="true">
                +
              </span>
              <span className="gate-name">Add profile</span>
            </button>
          </li>
        </ul>
      )}
      {locked && (
        <PinForm
          name={locked.name}
          onSubmit={pin => void choose(locked, pin)}
          onCancel={() => {
            setLocked(null);
            setError('');
          }}
        />
      )}
      {adding && (
        <NewProfileForm
          onCreated={onReady}
          onCancel={() => {
            setAdding(false);
            setError('');
          }}
          onError={setError}
        />
      )}
      {error && (
        <p className="notice" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}

function PinForm({
  name,
  onSubmit,
  onCancel,
}: {
  name: string;
  onSubmit: (pin: string) => void;
  onCancel: () => void;
}) {
  const [pin, setPin] = useState('');
  return (
    <form
      className="gate-form"
      onSubmit={event => {
        event.preventDefault();
        onSubmit(pin);
      }}
    >
      <label htmlFor="gate-pin">PIN for {name}</label>
      <input
        id="gate-pin"
        type="password"
        inputMode="numeric"
        autoComplete="off"
        maxLength={8}
        value={pin}
        autoFocus
        onChange={event => setPin(event.target.value.replace(/\D/g, ''))}
      />
      <div className="gate-actions">
        <button type="submit" className="button button-primary" disabled={!PIN.test(pin)}>
          Continue
        </button>
        <button type="button" className="button button-quiet" onClick={onCancel}>
          Back
        </button>
      </div>
    </form>
  );
}

export function NewProfileForm({
  onCreated,
  onCancel,
  onError,
}: {
  onCreated: () => void;
  onCancel: () => void;
  onError: (error: string) => void;
}) {
  const [name, setName] = useState('');
  const [pin, setPin] = useState('');
  const valid = name.trim().length > 0 && (pin === '' || PIN.test(pin));
  return (
    <form
      className="gate-form"
      onSubmit={async event => {
        event.preventDefault();
        try {
          await flicksApi.profiles.create(name.trim(), pin || null);
          onCreated();
        } catch (failure) {
          onError(message(failure));
        }
      }}
    >
      <label htmlFor="new-profile-name">Name</label>
      <input
        id="new-profile-name"
        maxLength={40}
        value={name}
        autoFocus
        onChange={event => setName(event.target.value)}
      />
      <label htmlFor="new-profile-pin">PIN (optional, 4–8 digits)</label>
      <input
        id="new-profile-pin"
        type="password"
        inputMode="numeric"
        autoComplete="new-password"
        maxLength={8}
        value={pin}
        onChange={event => setPin(event.target.value.replace(/\D/g, ''))}
      />
      <p className="fine">
        A PIN keeps others in your household out of your profile. It does not encrypt anything on this device.
      </p>
      <div className="gate-actions">
        <button type="submit" className="button button-primary" disabled={!valid}>
          Create profile
        </button>
        <button type="button" className="button button-quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
