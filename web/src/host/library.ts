import { createContext, useContext } from 'react';

import type { Content, MediaEntry, Progress, Rating } from '../api/types';

/** What any title-showing component needs: lookups, the user's ratings and progress, and actions. */
export interface Library {
  byId: ReadonlyMap<string, Content>;
  posters: ReadonlySet<string>;
  media: ReadonlyMap<string, MediaEntry>;
  feedback: Readonly<Record<string, Rating>>;
  progress: ReadonlyMap<string, Progress>;
  ratingBusy: boolean;
  rate: (id: string, value: Rating | 0) => void;
  openDetails: (id: string) => void;
  play: (id: string, fromStart?: boolean) => void;
}

export const LibraryContext = createContext<Library | null>(null);

export function useLibrary(): Library {
  const library = useContext(LibraryContext);
  if (!library) throw new Error('useLibrary must be used inside <LibraryContext.Provider>');
  return library;
}
