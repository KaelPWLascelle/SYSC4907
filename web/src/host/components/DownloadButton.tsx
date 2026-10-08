import type { Content } from '../../api/types';
import { Icon } from '../../components/Icon';
import { megabytes } from '../../lib/format';
import { useLibrary } from '../library';

/** Download a podcast episode, with its progress; renders nothing once it is downloaded (Play takes over). */
export function DownloadButton({ item }: { item: Content }) {
  const library = useLibrary();
  const status = library.downloads.get(item.id) ?? { state: 'remote' };
  if (status.state === 'ready') return null;
  if (status.state === 'queued' || status.state === 'downloading') {
    const label =
      status.state === 'queued'
        ? 'Waiting to download…'
        : status.received === 0
          ? 'Starting download…'
          : status.total
            ? `Downloading ${Math.floor((status.received / status.total) * 100)}%`
            : `Downloading ${megabytes(status.received)}`;
    return (
      <button type="button" className="button button-quiet" disabled>
        <Icon name="download" />
        <span role="status">{label}</span>
      </button>
    );
  }
  return (
    <>
      <button type="button" className="button button-primary" onClick={() => library.download(item.id)}>
        <Icon name="download" />
        {status.state === 'failed' ? 'Try the download again' : 'Download episode'}
      </button>
      {status.state === 'failed' && (
        <p className="field-error download-error" role="alert">
          {status.error}
        </p>
      )}
    </>
  );
}
