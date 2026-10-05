import { createContext, useContext } from 'react';

import type { Content, MediaEntry, Progress, Rating, TitleRef } from '../api/types';

/**
 * What any title-showing component needs: the user's ratings and progress, availability, and actions.
 * Components pass title objects around; the client never holds the whole catalogue.
 */
export interface Library {
  posters: ReadonlySet<string>;
  media: ReadonlyMap<string, MediaEntry>;
  feedback: Readonly<Record<string, Rating>>;
  progress: ReadonlyMap<string, Progress>;
  ratingBusy: boolean;
  rate: (id: string, value: Rating | 0) => void;
  openDetails: (item: Content) => void;
  play: (item: TitleRef, fromStart?: boolean) => void;
}

export const LibraryContext = createContext<Library | null>(null);

export function useLibrary(): Library {
  const library = useContext(LibraryContext);
  if (!library) throw new Error('useLibrary must be used inside <LibraryContext.Provider>');
  return library;
}
