import { useEffect, useRef, useState } from 'react';

import { EXPORT_URL, flicksApi } from '../../api/flicks';
import type { CurrentProfile } from '../../api/types';
import { Icon } from '../../components/Icon';

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const PIN = /^\d{4,8}$/;

interface ProfileMenuProps {
  open: boolean;
  profile: CurrentProfile;
  onClose: () => void;
  /** Show "Who's watching?" (after signing out of this profile). */
  onSwitch: () => void;
  /** The profile changed; `data` when its ratings or history did too (the page then starts over). */
  onChanged: (data: boolean) => void;
}

/** The current profile and its data: rename, PIN, export, import, clear and delete. */
export function ProfileMenu({ open, profile, onClose, onSwitch, onChanged }: ProfileMenuProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [status, setStatus] = useState('');
  const [name, setName] = useState(profile.name);
  const [pin, setPin] = useState('');
  const [currentPin, setCurrentPin] = useState('');
  const [importMode, setImportMode] = useState<'new' | 'merge'>('new');
  const [confirm, setConfirm] = useState<'clear' | 'delete' | null>(null);

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  /** Run an action and report it; `done` is the message, or makes one from the action's result. */
  const run = async <T,>(
    action: () => Promise<T>,
    done: string | ((result: T) => string),
    reload: false | 'profile' | 'data' = 'profile',
  ) => {
    try {
      const result = await action();
      setStatus(typeof done === 'string' ? done : done(result));
      setConfirm(null);
      setPin('');
      setCurrentPin('');
      if (reload) onChanged(reload === 'data');
      return true;
    } catch (failure) {
      setStatus(message(failure));
      return false;
    }
  };

  return (
    <dialog
      ref={dialog}
      className="details profile-menu"
      aria-labelledby="profile-menu-title"
      onClose={onClose}
      onClick={event => event.target === dialog.current && onClose()}
    >
      <button type="button" className="round details-close" aria-label="Close" onClick={onClose}>
        <Icon name="close" />
      </button>
      <div className="details-body">
        <p className="eyebrow">Profile on this device</p>
        <h2 id="profile-menu-title">{profile.name}</h2>
        <div className="details-actions">
          <button
            type="button"
            className="button button-quiet"
            onClick={() => void run(flicksApi.profiles.signOut, 'Signed out', false).then(ok => ok && onSwitch())}
          >
            Switch profile
          </button>
        </div>

        <h3>Name and PIN</h3>
        <form
          className="profile-form"
          onSubmit={event => {
            event.preventDefault();
            void run(() => flicksApi.profiles.update({ name: name.trim() }), 'Name saved');
          }}
        >
          <label htmlFor="profile-name">Name</label>
          <input id="profile-name" maxLength={40} value={name} onChange={event => setName(event.target.value)} />
          <button type="submit" className="button button-quiet" disabled={!name.trim() || name.trim() === profile.name}>
            Rename
          </button>
        </form>
        <form
          className="profile-form"
          onSubmit={event => {
            event.preventDefault();
            void run(
              () => flicksApi.profiles.update({ pin, current_pin: profile.locked ? currentPin : null }),
              'PIN saved',
            );
          }}
        >
          {profile.locked && (
            <>
              <label htmlFor="profile-current-pin">Current PIN</label>
              <input
                id="profile-current-pin"
                type="password"
                inputMode="numeric"
                autoComplete="off"
                maxLength={8}
                value={currentPin}
                onChange={event => setCurrentPin(event.target.value.replace(/\D/g, ''))}
              />
            </>
          )}
          <label htmlFor="profile-pin">{profile.locked ? 'New PIN' : 'PIN (4–8 digits)'}</label>
          <input
            id="profile-pin"
            type="password"
            inputMode="numeric"
            autoComplete="new-password"
            maxLength={8}
            value={pin}
            onChange={event => setPin(event.target.value.replace(/\D/g, ''))}
          />
          <button type="submit" className="button button-quiet" disabled={!PIN.test(pin)}>
            {profile.locked ? 'Change PIN' : 'Set PIN'}
          </button>
          {profile.locked && (
            <button
              type="button"
              className="button button-quiet"
              disabled={!PIN.test(currentPin)}
              onClick={() =>
                void run(() => flicksApi.profiles.update({ pin: null, current_pin: currentPin }), 'PIN removed')
              }
            >
              Remove PIN
            </button>
          )}
        </form>

        <h3>Your data</h3>
        <p className="fine">
          Your ratings and watch history are the whole of your taste profile: Flicks rebuilds recommendations from them,
          so this small file is everything another device needs.
        </p>
        <div className="details-actions">
          <a className="button button-quiet" href={EXPORT_URL} download>
            <Icon name="download" />
            Export ratings and history
          </a>
        </div>
        <fieldset className="profile-import">
          <legend>Import an export from another device</legend>
          <label>
            <input
              type="radio"
              name="import-mode"
              checked={importMode === 'new'}
              onChange={() => setImportMode('new')}
            />
            As a new profile
          </label>
          <label>
            <input
              type="radio"
              name="import-mode"
              checked={importMode === 'merge'}
              onChange={() => setImportMode('merge')}
            />
            Into {profile.name} (newer ratings win)
          </label>
          <label className="button button-quiet file-pick">
            Choose file…
            <input
              type="file"
              accept="application/json,.json"
              onChange={event => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (!file) return;
                void run(
                  () => flicksApi.profiles.import(file, importMode),
                  result =>
                    `Imported ${result.ratings} ratings and ${result.history} watch positions into ${result.profile.name}` +
                    (result.skipped ? ` (${result.skipped} titles are not in this catalogue)` : '') +
                    '.',
                  'data',
                );
              }}
            />
          </label>
        </fieldset>

        <h3>Clear or delete</h3>
        {confirm === null ? (
          <div className="details-actions">
            <button type="button" className="button button-quiet" onClick={() => setConfirm('clear')}>
              Clear ratings and history
            </button>
            {profile.count > 1 && (
              <button type="button" className="button button-danger" onClick={() => setConfirm('delete')}>
                Delete profile
              </button>
            )}
          </div>
        ) : (
          <div className="details-actions" role="group" aria-label="Confirm">
            <p className="notice">
              {confirm === 'clear'
                ? `Clear every rating and watch position in ${profile.name}? This cannot be undone. Export first to keep a copy.`
                : `Delete ${profile.name} with its ratings and history? This cannot be undone. Export first to keep a copy.`}
            </p>
            <button
              type="button"
              className="button button-danger"
              onClick={() =>
                confirm === 'clear'
                  ? void run(flicksApi.profiles.clearData, 'Ratings and history cleared', 'data')
                  : void run(flicksApi.profiles.remove, 'Profile deleted', false).then(ok => ok && onSwitch())
              }
            >
              {confirm === 'clear' ? 'Yes, clear' : 'Yes, delete'}
            </button>
            <button type="button" className="button button-quiet" onClick={() => setConfirm(null)}>
              Cancel
            </button>
          </div>
        )}
        <p className="menu-status" role="status" aria-live="polite">
          {status}
        </p>
      </div>
    </dialog>
  );
}
